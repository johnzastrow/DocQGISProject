# SPDX-License-Identifier: GPL-2.0-or-later
"""document_project(): the one engine behind the dialog, Processing, the console and tests.

    from DocQGISProject.core.runner import document_project
    result = document_project("/path/project.qgz", "/path/out")          # a file
    result = document_project(QgsProject.instance(), "/path/out")        # the open project

A project given as a path is read into a separate QgsProject with layers unresolved, so
nothing is loaded from a server unless the user opts in, and the live project is untouched.
The engine never modifies a project and never runs macros.
"""

import configparser
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from qgis.core import Qgis, QgsProject

from ..render.html_out import render_html
from ..render.json_out import render_json
from ..render.md_out import render_markdown
from ..render.pdf_out import render_pdf
from .artifacts import ArtifactSink
from .collectors.common import safe_message
from .collectors.layers import collect_layers, collect_tree
from .collectors.layouts import collect_layouts
from .collectors.maps import project_overview
from .collectors.fonts_files import collect_resources
from .collectors.tier_b import collect_tier_b
from .collectors.rebuild_payload import collect_rebuild
from .collectors.project import collect_bookmarks, collect_project, collect_relations, collect_themes, collect_variables
from .model import DocModel
from .options import DocOptions
from .safe_paths import OutputFolder

PROJECT_SUFFIXES = (".qgz", ".qgs")
OUTPUT_NAMES = {"json": "project.json", "markdown": "report.md", "html": "report.html", "pdf": "report.pdf"}
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Cancelled(Exception):
    """The user cancelled through the QgsFeedback object; nothing was written."""


@dataclass
class RunResult:
    files: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    redactions: dict = field(default_factory=dict)
    model: DocModel = None


def plugin_version():
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(_PLUGIN_DIR, "metadata.txt"), encoding="utf-8")
    return cp.get("general", "version", fallback="unknown")


def open_project(path):
    """Read a .qgz/.qgs into a new QgsProject without resolving any layer data source."""
    path = os.path.abspath(str(path))
    if not path.lower().endswith(PROJECT_SUFFIXES):
        raise ValueError(f"not a QGIS project file (.qgz or .qgs): {path}")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"project file not found: {path}")
    project = QgsProject()
    flags = Qgis.ProjectReadFlag.DontResolveLayers
    if not project.read(path, flags):
        raise ValueError(f"QGIS could not read the project: {project.error()}")
    return project


def collect(project, options, feedback=None, sink=None, screenshotter=None, unsaved=None):
    """Run every collector on an open project and return the DocModel.

    `screenshotter(project, model, options, sink, feedback)` takes the dialog screenshots. Only
    the plugin dialog passes one (gui/screenshots.py): core/ stays free of QGIS GUI code, and
    Processing, console and headless runs have no QGIS window to grab.

    `unsaved`: whether the project has changes not in its file. None means ask the project, but
    QGIS flags a project read with DontResolveLayers as dirty, and resolving layers does too, so
    document_project passes False for a project it has just read from a file.
    """
    sink = sink if sink is not None else ArtifactSink(images=options.images)
    model = DocModel()
    model.generator = {
        "plugin": "DocQGISProject",
        "plugin_version": plugin_version(),
        "qgis_version": Qgis.version(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    model.options = options.to_dict()

    def step(section, fn, *args):
        try:
            return fn(*args)
        except Exception as exc:  # principle 7: a failed section is reported, not fatal
            model.add_problem("error", section, f"could not be read: {safe_message(exc)}")
            return None

    if unsaved is None:
        unsaved = project.isDirty()  # before collectors resolve layers (which marks the project dirty)
    step("project", collect_project, project, model)
    model.layer_tree = step("layer tree", collect_tree, project)
    if feedback is not None:
        feedback.setProgress(10)
    if step("layers", collect_layers, project, model, options, feedback, sink) is False:
        raise Cancelled()
    step("variables", collect_variables, project, model, options.redact)
    step("relations", collect_relations, project, model)
    step("map themes", collect_themes, project, model)
    step("bookmarks", collect_bookmarks, project, model)
    if step("layouts", collect_layouts, project, model, options, sink, feedback) is False:
        raise Cancelled()
    if options.images:
        image = step("overview", project_overview, project, options.image_dpi)
        model.project.overview_image = sink.add_png("images/project_overview.png", image) if image else None
    step("resources", collect_resources, model, os.path.dirname(project.fileName()) if project.fileName() else None)
    if options.screenshots != "none":
        if screenshotter is None:
            model.add_problem(
                "info",
                "screenshots",
                "Dialog screenshots are taken only from the plugin dialog in the QGIS window; this run has none.",
            )
        elif step("screenshots", screenshotter, project, model, options, sink, feedback) is False:
            raise Cancelled()
    step("coverage", collect_tier_b, project, model, options, unsaved)
    if "json" in options.formats:
        step("rebuild", collect_rebuild, project, model, options)
    if not options.redact:
        model.add_problem("warning", "security", "Redaction was turned off: this output may contain credentials.")
    if sink.dropped:
        model.add_problem(
            "warning", "images", f"{sink.dropped} images or files were skipped: the size budget was reached."
        )
    return model


def document_project(project_or_path, output_folder, options=None, feedback=None, screenshotter=None):
    """Document a project into output_folder. Returns a RunResult; raises Cancelled on cancel."""
    options = (options or DocOptions()).validate()
    out = OutputFolder(output_folder, overwrite=options.overwrite)
    names = [OUTPUT_NAMES[f] for f in options.formats]
    out.check_writable(names)  # fail before doing any work if a file cannot be written

    from_file = not isinstance(project_or_path, QgsProject)
    project = open_project(project_or_path) if from_file else project_or_path
    sink = ArtifactSink(images=options.images)
    model = collect(project, options, feedback, sink, screenshotter, unsaved=False if from_file else None)
    if feedback is not None and feedback.isCanceled():
        raise Cancelled()
    # Every artifact name is checked before anything is written, so a conflict never leaves
    # a half-written folder. Images and styles are written first, then the reports.
    out.check_writable(list(sink.files))

    result = RunResult(model=model, problems=model.problems, redactions=model.redactions)
    for name, data in sink.files.items():
        result.files.append(out.write_bytes(name, data))
    for fmt in options.formats:
        if fmt == "json":
            data = render_json(model).encode("utf-8")
        elif fmt == "markdown":
            data = render_markdown(model).encode("utf-8")
        elif fmt == "html":
            data = render_html(model, sink.files).encode("utf-8")
        else:
            data = render_pdf(model, sink.files)
        result.files.append(out.write_bytes(OUTPUT_NAMES[fmt], data))
    if feedback is not None:
        feedback.setProgress(100)
    return result

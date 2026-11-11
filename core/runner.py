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

from ..render.json_out import render_json
from ..render.md_out import render_markdown
from .collectors.common import safe_message
from .collectors.layers import collect_layers, collect_tree
from .collectors.project import collect_bookmarks, collect_project, collect_relations, collect_themes, collect_variables
from .model import DocModel
from .options import DocOptions
from .safe_paths import OutputFolder

PROJECT_SUFFIXES = (".qgz", ".qgs")
OUTPUT_NAMES = {"json": "project.json", "markdown": "report.md"}
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


def collect(project, options, feedback=None):
    """Run every collector on an open project and return the DocModel."""
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

    step("project", collect_project, project, model)
    model.layer_tree = step("layer tree", collect_tree, project)
    if feedback is not None:
        feedback.setProgress(10)
    if step("layers", collect_layers, project, model, options, feedback) is False:
        raise Cancelled()
    step("variables", collect_variables, project, model, options.redact)
    step("relations", collect_relations, project, model)
    step("map themes", collect_themes, project, model)
    step("bookmarks", collect_bookmarks, project, model)
    if not options.redact:
        model.add_problem("warning", "security", "Redaction was turned off: this output may contain credentials.")
    return model


def document_project(project_or_path, output_folder, options=None, feedback=None):
    """Document a project into output_folder. Returns a RunResult; raises Cancelled on cancel."""
    options = (options or DocOptions()).validate()
    out = OutputFolder(output_folder, overwrite=options.overwrite)
    names = [OUTPUT_NAMES[f] for f in options.formats]
    out.check_writable(names)  # fail before doing any work if a file cannot be written

    project = project_or_path if isinstance(project_or_path, QgsProject) else open_project(project_or_path)
    model = collect(project, options, feedback)
    if feedback is not None and feedback.isCanceled():
        raise Cancelled()

    renderers = {"json": render_json, "markdown": render_markdown}
    result = RunResult(model=model, problems=model.problems, redactions=model.redactions)
    for fmt in options.formats:
        result.files.append(out.write_text(OUTPUT_NAMES[fmt], renderers[fmt](model)))
    if feedback is not None:
        feedback.setProgress(100)
    return result

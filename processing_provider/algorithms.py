# SPDX-License-Identifier: GPL-2.0-or-later
"""Processing algorithms (docs/DESIGN.md section 7).

docqgisproject:documentproject  - the documentation engine (core.runner.document_project)
docqgisproject:rebuildproject   - a new project from the JSON (core.rebuild.rebuild_project)

Both are thin wrappers: every rule lives in core/, so the dialog, Processing, qgis_process and
the Python console behave the same. Both run on the main thread (NoThreading): the open project
and its layers are not safe to read from a worker thread.
"""

from qgis.core import (
    Qgis,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputFile,
    QgsProcessingOutputFolder,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
)
from qgis.PyQt.QtCore import QCoreApplication

from ..core.collectors.common import safe_message
from ..core.options import ALL_FORMATS, DETAIL_LEVELS, SCREENSHOT_SCOPES, DocOptions
from ..core.paths import PATH_MODES
from ..core.uri_text import parse_map_arg

FORMAT_LABELS = ("JSON (machine, rebuild-grade)", "Markdown report", "HTML report", "PDF report")
DETAIL_LABELS = ("Summary", "Standard", "Full (every setting, Tier B appendix)")
PATH_LABELS = ("Relative to the project folder", "Full paths")
SCREENSHOT_LABELS = ("None", "Project dialogs", "Project and chosen layers", "Project and all layers")


def tr(text):
    return QCoreApplication.translate("DocQGISProject", text)


def _report_problems(problems, feedback):
    for p in problems:
        text = f"[{p.section}] {p.message}"
        if p.severity == "info":
            feedback.pushInfo(text)
        else:
            feedback.pushWarning(text)


class DocumentProjectAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    FORMATS = "FORMATS"
    DETAIL = "DETAIL"
    IMAGES = "IMAGES"
    IMAGE_DPI = "IMAGE_DPI"
    SCREENSHOTS = "SCREENSHOTS"
    EMBED_RESOURCES = "EMBED_RESOURCES"
    PATHS = "PATHS"
    LOAD_DATA = "LOAD_DATA"
    REDACT = "REDACT"
    INCLUDE_NETWORK_LAYERS = "INCLUDE_NETWORK_LAYERS"
    OVERWRITE = "OVERWRITE"

    def name(self):
        return "documentproject"

    def displayName(self):  # noqa: N802 - QGIS API name
        return tr("Document project")

    def group(self):
        return ""

    def groupId(self):  # noqa: N802 - QGIS API name
        return ""

    def shortHelpString(self):  # noqa: N802 - QGIS API name
        return tr(
            "Writes a description of a QGIS project: a JSON file complete enough to rebuild the project, "
            "and Markdown, HTML and PDF reports for people, with images of styles and print layouts.\n\n"
            "Leave the project file empty to document the open project. A project file is read on its own, "
            "without changing the open project, and its data are not opened from web services or databases "
            "unless you allow it.\n\n"
            "Paths are written relative to the project folder (./, ../) unless you choose full paths: the "
            "project file, data sources, SVG and image files and the rebuild data.\n\n"
            "Credentials are removed from every output unless you turn redaction off. Existing files in the "
            "output folder are never replaced unless this tool wrote them or you allow it.\n\n"
            "Dialog screenshots are only available from the Project > Document Project dialog."
        )

    def flags(self):
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def createInstance(self):  # noqa: N802 - QGIS API name
        return DocumentProjectAlgorithm()

    def initAlgorithm(self, config=None):  # noqa: N802 - QGIS API name
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT,
                tr("Project file (empty: the open project)"),
                behavior=QgsProcessingParameterFile.Behavior.File,
                fileFilter=tr("QGIS projects (*.qgz *.qgs)"),
                optional=True,
            )
        )
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_FOLDER, tr("Output folder")))
        self.addParameter(
            QgsProcessingParameterEnum(
                self.FORMATS,
                tr("Formats"),
                options=[tr(x) for x in FORMAT_LABELS],
                allowMultiple=True,
                defaultValue=list(range(len(ALL_FORMATS))),
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.DETAIL, tr("Detail level"), options=[tr(x) for x in DETAIL_LABELS], defaultValue=1
            )
        )
        self.addParameter(QgsProcessingParameterBoolean(self.IMAGES, tr("Images of styles and layouts"), True))
        self.addParameter(
            QgsProcessingParameterNumber(
                self.IMAGE_DPI,
                tr("Image resolution (dpi)"),
                type=Qgis.ProcessingNumberParameterType.Integer,
                defaultValue=120,
                minValue=48,
                maxValue=600,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.SCREENSHOTS,
                tr("Dialog screenshots (only in the plugin dialog; ignored here)"),
                options=[tr(x) for x in SCREENSHOT_LABELS],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PATHS, tr("Paths in the documentation"), options=[tr(x) for x in PATH_LABELS], defaultValue=0
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.EMBED_RESOURCES, tr("Embed SVG and image files used by the project in the JSON"), True
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(self.LOAD_DATA, tr("Open local data for feature counts and extents"), True)
        )
        self.addParameter(QgsProcessingParameterBoolean(self.REDACT, tr("Remove credentials (recommended)"), True))
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.INCLUDE_NETWORK_LAYERS, tr("Also open web services and databases"), False
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.OVERWRITE, tr("Replace files in the output folder not written by this tool"), False
            )
        )
        self.addOutput(QgsProcessingOutputFile("JSON", tr("JSON file")))
        self.addOutput(QgsProcessingOutputFile("MARKDOWN", tr("Markdown report")))
        self.addOutput(QgsProcessingOutputFile("HTML", tr("HTML report")))
        self.addOutput(QgsProcessingOutputFile("PDF", tr("PDF report")))
        self.addOutput(QgsProcessingOutputNumber("FILES", tr("Files written")))
        self.addOutput(QgsProcessingOutputNumber("WARNINGS", tr("Warnings")))
        self.addOutput(QgsProcessingOutputNumber("REDACTIONS", tr("Credentials removed")))
        self.addOutput(QgsProcessingOutputFolder("FOLDER", tr("Output folder")))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802 - QGIS API name
        from ..core.runner import OUTPUT_NAMES, Cancelled, document_project

        formats = self.parameterAsEnums(parameters, self.FORMATS, context)
        options = DocOptions(
            formats=tuple(ALL_FORMATS[i] for i in formats),
            detail=DETAIL_LEVELS[self.parameterAsEnum(parameters, self.DETAIL, context)],
            images=self.parameterAsBoolean(parameters, self.IMAGES, context),
            image_dpi=self.parameterAsInt(parameters, self.IMAGE_DPI, context),
            embed_resources=self.parameterAsBoolean(parameters, self.EMBED_RESOURCES, context),
            paths=PATH_MODES[self.parameterAsEnum(parameters, self.PATHS, context)],
            load_data=self.parameterAsBoolean(parameters, self.LOAD_DATA, context),
            redact=self.parameterAsBoolean(parameters, self.REDACT, context),
            include_network_layers=self.parameterAsBoolean(parameters, self.INCLUDE_NETWORK_LAYERS, context),
            overwrite=self.parameterAsBoolean(parameters, self.OVERWRITE, context),
        )
        scope = SCREENSHOT_SCOPES[self.parameterAsEnum(parameters, self.SCREENSHOTS, context)]
        if scope != "none":
            feedback.pushInfo(tr("Dialog screenshots are only taken from the plugin dialog; none in this run."))
        path = self.parameterAsFile(parameters, self.INPUT, context)
        folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        if path:
            target = path
        else:
            target = context.project()
            if target is None or (not target.mapLayers() and not target.fileName()):
                raise QgsProcessingException(tr("No project is open: give a project file."))
        try:
            result = document_project(target, folder, options, feedback)
        except Cancelled as exc:
            raise QgsProcessingException(tr("Cancelled; nothing was written.")) from exc
        except (ValueError, OSError) as exc:  # bad option, unreadable project, file conflict
            raise QgsProcessingException(safe_message(exc)) from exc
        _report_problems(result.problems, feedback)
        written = {f.replace("\\", "/").rsplit("/", 1)[-1]: f for f in result.files}
        out = {
            "FOLDER": folder,
            "FILES": len(result.files),
            "WARNINGS": sum(1 for p in result.problems if p.severity != "info"),
            "REDACTIONS": sum(result.redactions.values()),
        }
        for fmt, key in (("json", "JSON"), ("markdown", "MARKDOWN"), ("html", "HTML"), ("pdf", "PDF")):
            out[key] = written.get(OUTPUT_NAMES[fmt])
        out[self.OUTPUT_FOLDER] = folder
        return out


class RebuildProjectAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    SOURCE_MAP = "SOURCE_MAP"
    AUTH_MAP = "AUTH_MAP"
    ALLOW_ABSOLUTE = "ALLOW_ABSOLUTE"

    def name(self):
        return "rebuildproject"

    def displayName(self):  # noqa: N802 - QGIS API name
        return tr("Rebuild project from JSON")

    def group(self):
        return ""

    def groupId(self):  # noqa: N802 - QGIS API name
        return ""

    def shortHelpString(self):  # noqa: N802 - QGIS API name
        return tr(
            "Writes a new QGIS project (.qgz) from a project.json written by Document project.\n\n"
            "The JSON is checked in full first and refused if anything is unexpected. Project macros and "
            "other Python code are removed. An existing file is never replaced.\n\n"
            "Data are not in the JSON: the new project points at the same data sources. If the data moved, "
            "map folders in 'Data folder mapping' as old=new, separated by semicolons "
            "(for example /old/data=/new/data). Absolute paths must be mapped.\n\n"
            "Credentials are not in the JSON either. For a source that needs a login, give a QGIS "
            "authentication configuration in 'Authentication mapping' as source=config id "
            "(for example s3=ab12cd3). The source ids are listed in the report appendix."
        )

    def flags(self):
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def createInstance(self):  # noqa: N802 - QGIS API name
        return RebuildProjectAlgorithm()

    def initAlgorithm(self, config=None):  # noqa: N802 - QGIS API name
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT,
                tr("project.json"),
                behavior=QgsProcessingParameterFile.Behavior.File,
                fileFilter=tr("DocQGISProject JSON (*.json)"),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(self.SOURCE_MAP, tr("Data folder mapping (old=new;old2=new2)"), optional=True)
        )
        self.addParameter(
            QgsProcessingParameterString(self.AUTH_MAP, tr("Authentication mapping (s3=configid;...)"), optional=True)
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ALLOW_ABSOLUTE,
                tr("Allow absolute data paths without a mapping (only for a JSON you trust)"),
                False,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(self.OUTPUT, tr("New project"), fileFilter=tr("QGIS project (*.qgz)"))
        )
        self.addOutput(QgsProcessingOutputString("NEEDS_CREDENTIALS", tr("Sources that need credentials")))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802 - QGIS API name
        from ..core.rebuild import RebuildError, rebuild_project

        try:
            source_map = parse_map_arg(self.parameterAsString(parameters, self.SOURCE_MAP, context))
            auth_map = parse_map_arg(self.parameterAsString(parameters, self.AUTH_MAP, context))
            result = rebuild_project(
                self.parameterAsFile(parameters, self.INPUT, context),
                self.parameterAsFileOutput(parameters, self.OUTPUT, context),
                source_map=source_map,
                auth_map=auth_map,
                feedback=feedback,
                allow_absolute=self.parameterAsBoolean(parameters, self.ALLOW_ABSOLUTE, context),
            )
        except (RebuildError, ValueError, OSError) as exc:
            raise QgsProcessingException(safe_message(exc)) from exc
        for severity, message in result.problems:
            (feedback.pushInfo if severity == "info" else feedback.pushWarning)(message)
        return {self.OUTPUT: result.project_file, "NEEDS_CREDENTIALS": ",".join(result.needs_credentials)}

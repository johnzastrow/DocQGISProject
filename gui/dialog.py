# SPDX-License-Identifier: GPL-2.0-or-later
"""The Document Project dialog (docs/DESIGN.md section 7): the same options as the Processing
algorithm, plus a project picker, progress, Cancel, Open report, a coverage summary and the
dialog screenshots that only a GUI run can take.

The run happens on the main thread (the open project and its layers are not safe to read from
a worker thread). The dialog is modal, so while it runs the rest of QGIS takes no input: nobody
can remove a layer in the middle of a run. Progress updates let the dialog itself repaint and
receive the Cancel click.

Every option is saved in QgsSettings under "DocQGISProject/" and restored next time.
"""

import os

from qgis.core import QgsFeedback, QgsProject, QgsSettings
from qgis.gui import QgsFileWidget
from qgis.PyQt.QtCore import QCoreApplication, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core.collectors.common import safe_message
from ..core.options import ALL_FORMATS, DETAIL_LEVELS, SCREENSHOT_SCOPES, DocOptions

KEY = "DocQGISProject/"
FORMAT_LABELS = {"json": "JSON (for programs, rebuild)", "markdown": "Markdown", "html": "HTML", "pdf": "PDF"}
DETAIL_LABELS = {"summary": "Summary", "standard": "Standard", "full": "Full (every setting)"}
SCREENSHOT_LABELS = {
    "none": "None",
    "project": "Project dialogs and layouts",
    "layers": "Project, layouts and the layers ticked below",
    "all": "Project, layouts and every layer",
}


def tr(text):
    return QCoreApplication.translate("DocQGISProject", text)


def _bool(value, default):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).lower() in ("true", "1", "yes")


class DocumentDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.feedback = None
        self.running = False
        self.last_files = []
        self.setWindowTitle(tr("Document Project"))
        self.setObjectName("DocQGISProjectDialog")
        self._build()
        self._load_settings()
        self._update_state()

    # ------------------------------------------------------------------ layout
    def _build(self):
        main = QVBoxLayout(self)

        src = QGroupBox(tr("Project"))
        sl = QVBoxLayout(src)
        self.rb_open = QRadioButton(tr("The open project"))
        self.rb_open.setToolTip(tr("Document the project open in QGIS, including unsaved changes to its layers."))
        self.rb_file = QRadioButton(tr("A project file"))
        self.rb_file.setToolTip(
            tr("Document a .qgz or .qgs file. It is read on its own; the open project is not changed.")
        )
        group = QButtonGroup(self)
        group.addButton(self.rb_open)
        group.addButton(self.rb_file)
        self.project_file = QgsFileWidget()
        self.project_file.setFilter(tr("QGIS projects (*.qgz *.qgs)"))
        self.project_file.setToolTip(tr("The project file to document."))
        sl.addWidget(self.rb_open)
        row = QHBoxLayout()
        row.addWidget(self.rb_file)
        row.addWidget(self.project_file, 1)
        sl.addLayout(row)
        main.addWidget(src)

        out = QGroupBox(tr("Output"))
        form = QFormLayout(out)
        self.out_folder = QgsFileWidget()
        self.out_folder.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        self.out_folder.setToolTip(
            tr("Folder for the reports and images. Files in it are only replaced if this plugin wrote them.")
        )
        form.addRow(tr("Folder"), self.out_folder)
        fmts = QHBoxLayout()
        self.fmt_boxes = {}
        tips = {
            "json": tr("A JSON file for programs, complete enough to rebuild the project."),
            "markdown": tr("A plain-text report, readable as is and in wikis."),
            "html": tr("A single web page with a table of contents and images inside it."),
            "pdf": tr("A printable report with page numbers."),
        }
        for f in ALL_FORMATS:
            box = QCheckBox(tr(FORMAT_LABELS[f]))
            box.setToolTip(tips[f])
            self.fmt_boxes[f] = box
            fmts.addWidget(box)
        form.addRow(tr("Formats"), fmts)
        self.detail = QComboBox()
        for level in DETAIL_LEVELS:
            self.detail.addItem(tr(DETAIL_LABELS[level]), level)
        self.detail.setToolTip(
            tr(
                "Summary: the main facts. Standard: every setting you changed. "
                "Full: also every element of the project file the chapters do not explain."
            )
        )
        form.addRow(tr("Detail"), self.detail)
        main.addWidget(out)

        opts = QGroupBox(tr("Options"))
        ol = QFormLayout(opts)
        self.images = QCheckBox(tr("Images of styles, maps and layouts"))
        self.images.setToolTip(tr("Legend and symbol pictures, layer maps and print layout pages."))
        self.dpi = QSpinBox()
        self.dpi.setRange(48, 600)
        self.dpi.setSuffix(" dpi")
        self.dpi.setToolTip(tr("Resolution of the images. Higher is sharper, slower and larger."))
        row = QHBoxLayout()
        row.addWidget(self.images)
        row.addWidget(self.dpi)
        ol.addRow(row)
        self.paths = QComboBox()
        self.paths.addItem(tr("Relative to the project folder (./data, ../data)"), "relative")
        self.paths.addItem(tr("Full paths"), "absolute")
        self.paths.setToolTip(
            tr(
                "How file paths are written in the reports and the JSON: the project file, data sources, "
                "SVG and image files and the rebuild data. Relative paths keep your folder names private and "
                "stay valid when the whole folder moves. Full paths show exactly where each file is on this "
                "computer."
            )
        )
        ol.addRow(tr("Paths"), self.paths)
        self.embed = QCheckBox(tr("Put SVG and image files used by the project inside the JSON"))
        self.embed.setToolTip(tr("So a rebuild elsewhere has them (up to 20 MB in total). Fonts are only listed."))
        self.load_data = QCheckBox(tr("Open local data for feature counts and extents"))
        self.load_data.setToolTip(tr("Off: document from the project file alone, faster and without opening data."))
        self.redact = QCheckBox(tr("Remove credentials (recommended)"))
        self.redact.setToolTip(
            tr("Remove passwords, user names, tokens and keys from every output. Turn off only for private use.")
        )
        self.network = QCheckBox(tr("Also open web services and databases"))
        self.network.setToolTip(
            tr("Contact servers to read counts and extents of remote layers. Off: nothing is sent over the network.")
        )
        self.overwrite = QCheckBox(tr("Replace files in the folder that this plugin did not write"))
        self.overwrite.setToolTip(tr("Off: the run stops instead of replacing a file it did not create."))
        for w in (self.embed, self.load_data, self.redact, self.network, self.overwrite):
            ol.addRow(w)
        main.addWidget(opts)

        shots = QGroupBox(tr("Dialog screenshots"))
        shl = QVBoxLayout(shots)
        self.shots = QComboBox()
        for scope in SCREENSHOT_SCOPES:
            self.shots.addItem(tr(SCREENSHOT_LABELS[scope]), scope)
        self.shots.setToolTip(
            tr(
                "Pictures of the QGIS dialogs for this project. Each dialog opens briefly and closes with Cancel, "
                "so nothing changes. Pages with data sources or logins are skipped and paths are blacked out. "
                "Only for the open project."
            )
        )
        self.layer_list = QListWidget()
        self.layer_list.setToolTip(tr("Tick the layers whose properties dialog should be pictured."))
        self.layer_list.setMaximumHeight(110)
        self.shots_note = QLabel("")
        self.shots_note.setWordWrap(True)
        self.shots_note.setToolTip(tr("Why screenshots are not available with the current choices."))
        shl.addWidget(self.shots)
        shl.addWidget(self.shots_note)
        shl.addWidget(self.layer_list)
        main.addWidget(shots)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setToolTip(tr("Progress of the current run."))
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status.setToolTip(tr("Result of the last run: files written, coverage, warnings."))
        main.addWidget(self.progress)
        main.addWidget(self.status)

        buttons = QHBoxLayout()
        self.btn_run = QPushButton(tr("Document"))
        self.btn_run.setToolTip(tr("Write the documentation with these options."))
        self.btn_run.setDefault(True)
        self.btn_cancel = QPushButton(tr("Cancel run"))
        self.btn_cancel.setToolTip(tr("Stop the run. Nothing is written when a run is cancelled."))
        self.btn_open = QPushButton(tr("Open report"))
        self.btn_open.setToolTip(tr("Open the report of the last run (HTML, else PDF, else Markdown)."))
        self.btn_close = QPushButton(tr("Close"))
        self.btn_close.setToolTip(tr("Close this dialog. The options are remembered."))
        for b in (self.btn_run, self.btn_cancel, self.btn_open):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_close)
        main.addLayout(buttons)

        self.btn_run.clicked.connect(self.run)
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_open.clicked.connect(self.open_report)
        self.btn_close.clicked.connect(self.reject)
        for w in (self.rb_open, self.rb_file, self.images):
            w.toggled.connect(self._update_state)
        self.shots.currentIndexChanged.connect(self._update_state)
        self.project_file.fileChanged.connect(self._update_state)
        self.out_folder.fileChanged.connect(self._update_state)
        for box in self.fmt_boxes.values():
            box.toggled.connect(self._update_state)

    # ------------------------------------------------------------------ settings
    def _load_settings(self):
        s = QgsSettings()
        d = DocOptions()
        self.rb_file.setChecked(s.value(KEY + "source", "open") == "file")
        self.rb_open.setChecked(not self.rb_file.isChecked())
        self.project_file.setFilePath(s.value(KEY + "project_file", ""))
        self.out_folder.setFilePath(s.value(KEY + "output_folder", "") or self._suggest_folder())
        saved = s.value(KEY + "formats", ",".join(d.formats)) or ""
        saved = [f for f in str(saved).split(",") if f in ALL_FORMATS] or list(d.formats)
        for f, box in self.fmt_boxes.items():
            box.setChecked(f in saved)
        self._select(self.detail, s.value(KEY + "detail", d.detail))
        self.images.setChecked(_bool(s.value(KEY + "images"), d.images))
        try:
            self.dpi.setValue(int(s.value(KEY + "image_dpi", d.image_dpi)))
        except (TypeError, ValueError):
            self.dpi.setValue(d.image_dpi)
        self.embed.setChecked(_bool(s.value(KEY + "embed_resources"), d.embed_resources))
        self.load_data.setChecked(_bool(s.value(KEY + "load_data"), d.load_data))
        self.redact.setChecked(_bool(s.value(KEY + "redact"), d.redact))
        self.network.setChecked(_bool(s.value(KEY + "include_network_layers"), d.include_network_layers))
        self.overwrite.setChecked(_bool(s.value(KEY + "overwrite"), d.overwrite))
        self._select(self.shots, s.value(KEY + "screenshots", d.screenshots))
        self._select(self.paths, s.value(KEY + "paths", d.paths))
        self._fill_layers()

    def _save_settings(self):
        s = QgsSettings()
        s.setValue(KEY + "source", "file" if self.rb_file.isChecked() else "open")
        s.setValue(KEY + "project_file", self.project_file.filePath())
        s.setValue(KEY + "output_folder", self.out_folder.filePath())
        s.setValue(KEY + "formats", ",".join(self._formats()))
        s.setValue(KEY + "detail", self.detail.currentData())
        s.setValue(KEY + "images", self.images.isChecked())
        s.setValue(KEY + "image_dpi", self.dpi.value())
        s.setValue(KEY + "embed_resources", self.embed.isChecked())
        s.setValue(KEY + "load_data", self.load_data.isChecked())
        s.setValue(KEY + "redact", self.redact.isChecked())
        s.setValue(KEY + "include_network_layers", self.network.isChecked())
        s.setValue(KEY + "overwrite", self.overwrite.isChecked())
        s.setValue(KEY + "screenshots", self.shots.currentData())
        s.setValue(KEY + "paths", self.paths.currentData())

    @staticmethod
    def _select(combo, value):
        i = combo.findData(value)
        combo.setCurrentIndex(i if i >= 0 else 0)

    @staticmethod
    def _suggest_folder():
        path = QgsProject.instance().fileName()
        if not path:
            return ""
        stem = os.path.splitext(os.path.basename(path))[0]
        return os.path.join(os.path.dirname(path), f"{stem}_documentation")

    def _fill_layers(self):
        self.layer_list.blockSignals(True)  # skill pitfall: never clear a list with live selection signals
        self.layer_list.clear()
        layers = [lyr for lyr in QgsProject.instance().mapLayers().values() if lyr is not None]
        for lyr in sorted(layers, key=lambda x: x.name().lower()):
            item = QListWidgetItem(lyr.name())
            item.setData(Qt.ItemDataRole.UserRole, lyr.id())
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.layer_list.addItem(item)
        self.layer_list.blockSignals(False)

    # ------------------------------------------------------------------ state
    def _formats(self):
        return [f for f in ALL_FORMATS if self.fmt_boxes[f].isChecked()]

    def _chosen_layers(self):
        out = []
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def _update_state(self, *_args):
        idle = not self.running
        open_project = self.rb_open.isChecked()
        for w in (
            self.rb_open,
            self.rb_file,
            self.out_folder,
            self.detail,
            self.images,
            self.embed,
            self.load_data,
            self.redact,
            self.network,
            self.overwrite,
            self.paths,
            *self.fmt_boxes.values(),
        ):
            w.setEnabled(idle)
        self.project_file.setEnabled(idle and not open_project)
        self.dpi.setEnabled(idle and self.images.isChecked())
        shots_possible = idle and open_project and self.images.isChecked()
        self.shots.setEnabled(shots_possible)
        self.layer_list.setEnabled(shots_possible and self.shots.currentData() == "layers")
        # Say why the screenshot choice is greyed out, instead of leaving a silent disabled box.
        if not open_project:
            note = tr(
                "Screenshots need the project open in QGIS: open the project file, then choose "
                "'The open project' above."
            )
        elif not self.images.isChecked():
            note = tr("Screenshots need 'Images of styles, maps and layouts' turned on.")
        else:
            note = ""
        self.shots_note.setText(note)
        self.shots_note.setVisible(bool(note))
        ready = bool(self._formats()) and bool(self.out_folder.filePath())
        if not open_project:
            ready = ready and self.project_file.filePath().lower().endswith((".qgz", ".qgs"))
        self.btn_run.setEnabled(idle and ready)
        self.btn_cancel.setEnabled(self.running)
        self.btn_close.setEnabled(idle)
        self.btn_open.setEnabled(idle and bool(self._report_path()))

    def options(self):
        """DocOptions from the controls (validated by the caller)."""
        open_project = self.rb_open.isChecked()
        scope = self.shots.currentData() if (open_project and self.images.isChecked()) else "none"
        return DocOptions(
            formats=tuple(self._formats()),
            detail=self.detail.currentData(),
            images=self.images.isChecked(),
            image_dpi=self.dpi.value(),
            embed_resources=self.embed.isChecked(),
            paths=self.paths.currentData(),
            load_data=self.load_data.isChecked(),
            redact=self.redact.isChecked(),
            include_network_layers=self.network.isChecked(),
            overwrite=self.overwrite.isChecked(),
            screenshots=scope,
            screenshot_layers=tuple(self._chosen_layers()) if scope == "layers" else (),
        )

    # ------------------------------------------------------------------ run
    def _progress(self, value):
        self.progress.setValue(int(value))
        # Repaint and accept the Cancel click. The dialog is modal, so the rest of QGIS takes no input.
        QCoreApplication.processEvents()

    def run(self):
        from ..core.runner import Cancelled, document_project
        from .screenshots import Screenshotter

        try:
            options = self.options().validate()
        except ValueError as exc:
            self.status.setText(tr("Cannot start: ") + safe_message(exc))
            return
        self._save_settings()
        target = QgsProject.instance() if self.rb_open.isChecked() else self.project_file.filePath()
        self.running = True
        self.feedback = QgsFeedback()
        self.feedback.progressChanged.connect(self._progress)
        self.progress.setValue(0)
        self.status.setText(tr("Working..."))
        self._update_state()
        shooter = Screenshotter(self.iface) if options.screenshots != "none" else None
        try:
            result = document_project(target, self.out_folder.filePath(), options, self.feedback, shooter)
        except Cancelled:
            self.status.setText(tr("Cancelled. Nothing was written."))
            self.progress.setValue(0)
        except Exception as exc:  # shown to the user, never a traceback dialog
            self.status.setText(tr("The run failed: ") + safe_message(exc))
        else:
            self.last_files = result.files
            self.status.setText(self._summary(result))
            self.progress.setValue(100)
        finally:
            self.running = False
            self.feedback = None
            self._update_state()

    def _summary(self, result):
        cov = result.model.coverage or {}
        warnings = sum(1 for p in result.problems if p.severity != "info")
        parts = [tr("Wrote {n} files.").format(n=len(result.files))]
        if cov:
            parts.append(tr("The report explains {p} % of the project file.").format(p=cov.get("percent_claimed")))
        parts.append(tr("{n} warnings (see the report).").format(n=warnings) if warnings else tr("No warnings."))
        removed = sum(result.redactions.values())
        if removed:
            parts.append(tr("{n} credentials removed.").format(n=removed))
        shots = (result.model.screenshots or {}).get("items") or []
        if shots:
            taken = sum(1 for i in shots if i.get("image"))
            parts.append(tr("{n} dialog screenshots.").format(n=taken))
        return " ".join(parts)

    def cancel(self):
        if self.feedback is not None:
            self.feedback.cancel()
            self.status.setText(tr("Cancelling..."))

    def _report_path(self):
        names = {os.path.basename(f): f for f in self.last_files}
        for name in ("report.html", "report.pdf", "report.md"):
            if name in names and os.path.isfile(names[name]):
                return names[name]
        return None

    def open_report(self):
        path = self._report_path()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------ closing
    def reject(self):
        if self.running:  # closing mid-run (Esc or the window button) cancels instead
            self.cancel()
            return
        self._save_settings()
        super().reject()

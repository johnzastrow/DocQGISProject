"""P6: the Document Project dialog and the dialog screenshots.

The real QGIS properties dialogs need the QGIS application window, so the screenshot tests use
stand-ins with the same structure (a page list mOptionsListWidget plus a page stack
mOptionsStackedWidget, opened modally with exec()), and a stand-in layout designer with an
ItemDock. That proves the mechanics: modal grab, page stepping, skipping, masking, always
closing with reject. The look of the real dialogs is checked in the GUI click test.
"""

import json

import pytest

KEY = "DocQGISProject"


@pytest.fixture(autouse=True)
def _close_windows(qgis_app):
    """Delete every window a test created before QGIS shuts down (a live top-level widget at
    exitQgis crashes the process at exit)."""
    yield
    from qgis.PyQt.QtCore import QCoreApplication, QEvent
    from qgis.PyQt.QtWidgets import QApplication

    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


@pytest.fixture
def clean_settings(qgis_app):
    """Keep the user's real QGIS settings untouched: save and restore the plugin's keys."""
    from qgis.core import QgsSettings

    s = QgsSettings()
    s.beginGroup(KEY)
    saved = {k: s.value(k) for k in s.allKeys()}
    s.endGroup()
    s.remove(KEY)
    yield
    s.remove(KEY)
    for k, v in saved.items():
        s.setValue(f"{KEY}/{k}", v)


class _Bar:
    def pushMessage(self, *a, **k):  # noqa: N802
        pass


def _options_dialog(pages, rejected):
    """A modal stand-in for QgsOptionsDialogBase: page titles -> widget factories."""
    from qgis.PyQt.QtWidgets import QDialog, QHBoxLayout, QListWidget, QStackedWidget

    dlg = QDialog()
    lay = QHBoxLayout(dlg)
    lst = QListWidget()
    lst.setObjectName("mOptionsListWidget")
    stack = QStackedWidget()
    stack.setObjectName("mOptionsStackedWidget")
    for title, make in pages:
        lst.addItem(title)
        stack.addWidget(make())
    lst.currentRowChanged.connect(stack.setCurrentIndex)
    lay.addWidget(lst)
    lay.addWidget(stack)
    dlg.resize(500, 300)
    dlg.finished.connect(lambda code: rejected.append(code))
    return dlg


def _page(*texts):
    def make():
        from qgis.PyQt.QtWidgets import QLineEdit, QVBoxLayout, QWidget

        w = QWidget()
        lay = QVBoxLayout(w)
        for t in texts:
            lay.addWidget(QLineEdit(t))
        return w

    return make


class _Designer:
    def __init__(self, closed):
        from qgis.PyQt.QtWidgets import QDockWidget, QLabel, QMainWindow

        self._win = QMainWindow()
        dock = QDockWidget("Item Properties", self._win)
        dock.setObjectName("ItemDock")
        dock.setWidget(QLabel("Picture: ./assets/north.svg"))
        self._win.addDockWidget(self._win_area(), dock)
        self._win.resize(600, 400)
        self._win.show()
        self.selected = []
        self._closed = closed

    @staticmethod
    def _win_area():
        from qgis.PyQt.QtCore import Qt

        return Qt.DockWidgetArea.RightDockWidgetArea

    def window(self):
        return self._win

    def selectItems(self, items):  # noqa: N802
        self.selected.append(items)

    def close(self):
        self._win.close()
        self._closed.append(True)


class FakeIface:
    """The QgisInterface calls the dialog and the screenshotter use."""

    def __init__(self):
        from qgis.PyQt.QtWidgets import QMainWindow

        self._main = QMainWindow()
        self.rejected = []
        self.closed = []
        self.designers = []

    def mainWindow(self):  # noqa: N802
        return self._main

    def messageBar(self):  # noqa: N802
        return _Bar()

    def showProjectPropertiesDialog(self, page=""):  # noqa: N802
        dlg = _options_dialog(
            [
                ("General", _page("Fixture title", "/home/someone/projects/fixture.qgz")),
                ("Data Sources", _page("./fixture_data.gpkg")),
                ("Variables", _page("region")),
            ],
            self.rejected,
        )
        dlg.exec()

    def showLayerProperties(self, layer, page=""):  # noqa: N802
        dlg = _options_dialog(
            [
                ("Information", _page(layer.source())),
                ("Source", _page(layer.source())),
                ("Symbology", _page("Single symbol")),
                ("Labels", _page("No labels")),
            ],
            self.rejected,
        )
        dlg.exec()

    def openLayoutDesigner(self, layout):  # noqa: N802
        d = _Designer(self.closed)
        self.designers.append(d)
        return d


# --------------------------------------------------------------------------- masking


def test_grab_masks_paths_and_logins(qgis_app, plugin_pkg):
    from qgis.PyQt.QtWidgets import QLineEdit, QVBoxLayout, QWidget

    from DocQGISProject.gui.screenshots import grab_masked

    w = QWidget()
    lay = QVBoxLayout(w)
    plain = QLineEdit("Single symbol")
    secret = QLineEdit("dbname='gis' host=db.internal user='bob'")
    path = QLineEdit("C:\\Users\\bob\\data.gpkg")
    for x in (plain, secret, path):
        lay.addWidget(x)
    w.resize(300, 120)
    w.show()
    image, masked = grab_masked(w)
    assert masked == 2
    ratio = image.devicePixelRatio() or 1.0

    def pixel(widget):
        c = widget.geometry().center()
        return image.pixelColor(int(c.x() * ratio), int(c.y() * ratio)).getRgb()[:3]

    assert pixel(secret) == (40, 40, 40) and pixel(path) == (40, 40, 40)
    assert pixel(plain) != (40, 40, 40)
    w.close()


def test_grab_masks_secret_rows_in_lists(qgis_app, plugin_pkg):
    """The Variables page lists names and values in a tree: a secret-named variable's whole row
    (its value included) is blacked out; an ordinary variable stays readable."""
    from qgis.PyQt.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

    from DocQGISProject.gui.screenshots import grab_masked

    w = QWidget()
    tree = QTreeWidget()
    tree.setColumnCount(2)
    plain = QTreeWidgetItem(["region", "Maine"])
    secret = QTreeWidgetItem(["service_token", "VAR-TOKEN-000"])  # pragma: allowlist secret
    tree.addTopLevelItems([plain, secret])
    QVBoxLayout(w).addWidget(tree)
    w.resize(400, 200)
    w.show()
    image, masked = grab_masked(w)
    assert masked == 1
    ratio = image.devicePixelRatio() or 1.0
    vp = tree.viewport()

    def pixel(row, col):
        c = vp.mapTo(w, tree.visualRect(tree.model().index(row, col)).center())
        return image.pixelColor(int(c.x() * ratio), int(c.y() * ratio)).getRgb()[:3]

    assert pixel(1, 1) == (40, 40, 40) and pixel(1, 0) == (40, 40, 40)  # secret row: name and value
    assert pixel(0, 1) != (40, 40, 40)  # ordinary variable
    w.close()


# --------------------------------------------------------------------------- screenshotter


@pytest.fixture
def live_layout_project(qgis_app, fixtures_dir):
    from qgis.core import QgsProject

    project = QgsProject.instance()
    assert project.read(str(fixtures_dir / "layout.qgz"))
    yield project
    project.clear()


def test_screenshots_end_to_end(plugin_pkg, live_layout_project, tmp_path):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project
    from DocQGISProject.gui.screenshots import SKIP_REASON, Screenshotter

    iface = FakeIface()
    layer_ids = list(live_layout_project.mapLayers())
    options = DocOptions(
        formats=("json", "markdown"), screenshots="layers", screenshot_layers=tuple(layer_ids[:2]), image_dpi=48
    )
    result = document_project(live_layout_project, str(tmp_path), options, screenshotter=Screenshotter(iface))
    items = result.model.screenshots["items"]

    project_pages = [i for i in items if i["kind"] == "project"]
    assert [i["page"] for i in project_pages] == ["General", "Data Sources", "Variables"]
    assert project_pages[1]["skipped"] == SKIP_REASON and project_pages[1]["image"] is None
    assert project_pages[0]["masked"] == 1  # the project path

    layer_pages = [i for i in items if i["kind"] == "layer"]
    assert len({i["target_id"] for i in layer_pages}) == 2
    assert all(i["skipped"] for i in layer_pages if i["page"] in ("Information", "Source"))
    assert all(i["image"] for i in layer_pages if i["page"] in ("Symbology", "Labels"))

    layout_pages = [i for i in items if i["kind"] == "layout"]
    assert layout_pages and layout_pages[0]["page"] == "Layout Designer"
    assert any(i["page"].startswith("Item: ") and i["image"] for i in layout_pages)

    # Every dialog was closed with reject (0), every designer closed.
    assert iface.rejected and set(iface.rejected) == {0}
    assert len(iface.rejected) == 1 + 2
    assert len(iface.closed) == len(iface.designers) >= 1
    from qgis.PyQt.QtWidgets import QApplication

    assert QApplication.activeModalWidget() is None

    for i in items:
        if i["image"]:
            assert (tmp_path / i["image"]).is_file()
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    import re

    appendix = re.search(r"^## \d+\. Appendix: QGIS dialog screenshots$", md, re.M).start()
    # Woven in: each screenshot sits in the section that documents its page, before the appendix.
    assert md.index("](images/screenshots/project_01.png)") < appendix
    for i in layer_pages:
        if i["image"]:
            pos = md.index(f"]({i['image']})")
            section = md.rfind("\n#### ", 0, pos)
            assert pos < appendix, i["page"]
            if i["page"] == "Symbology":
                assert md[section : section + 60].split("\n")[1].endswith("Symbology")
    assert any(f"]({i['image']})" in md[:appendix] for i in layout_pages if i["image"])
    data = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert data["screenshots"]["environment"]["QGIS"]


def test_screenshots_need_the_open_project(plugin_pkg, fixtures_dir, tmp_path):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project
    from DocQGISProject.gui.screenshots import Screenshotter

    iface = FakeIface()
    result = document_project(
        str(fixtures_dir / "basic.qgz"),
        str(tmp_path),
        DocOptions(formats=("json",), screenshots="project"),
        screenshotter=Screenshotter(iface),
    )
    assert not iface.rejected  # no dialog was opened for a project file
    assert any(p.section == "screenshots" for p in result.problems)


def test_screenshots_without_gui_is_a_note(plugin_pkg, fixtures_dir, tmp_path):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project

    result = document_project(
        str(fixtures_dir / "basic.qgz"), str(tmp_path), DocOptions(formats=("json",), screenshots="all")
    )
    assert any(p.section == "screenshots" and p.severity == "info" for p in result.problems)


def test_error_inside_dialog_still_closes_it(qgis_app, plugin_pkg):
    from qgis.PyQt.QtWidgets import QApplication

    from DocQGISProject.gui.screenshots import grab_modal

    iface = FakeIface()

    class Boom(Exception):
        pass

    def handle(dialog):
        raise Boom()

    with pytest.raises(Boom):
        grab_modal(lambda: iface.showProjectPropertiesDialog(""), handle)
    assert iface.rejected == [0]
    assert QApplication.activeModalWidget() is None


def test_no_dialog_opens(qgis_app, plugin_pkg):
    from DocQGISProject.gui.screenshots import grab_modal

    assert grab_modal(lambda: None, lambda d: "grabbed") is None


# --------------------------------------------------------------------------- dialog


@pytest.fixture
def dialog(plugin_pkg, clean_settings):
    from DocQGISProject.gui.dialog import DocumentDialog

    dlg = DocumentDialog(FakeIface())
    yield dlg
    dlg.deleteLater()


def test_every_control_has_a_tooltip(dialog):
    from qgis.gui import QgsFileWidget
    from qgis.PyQt.QtWidgets import (
        QCheckBox,
        QComboBox,
        QListWidget,
        QProgressBar,
        QPushButton,
        QRadioButton,
        QSpinBox,
    )

    controls = []
    for cls in (QCheckBox, QComboBox, QPushButton, QRadioButton, QSpinBox, QListWidget, QProgressBar, QgsFileWidget):
        controls += [w for w in dialog.findChildren(cls) if w.parent() is not None and not _inside_file_widget(w)]
    missing = [f"{type(w).__name__} {getattr(w, 'text', lambda: '')()}" for w in controls if not w.toolTip()]
    assert controls and not missing, missing


def _inside_file_widget(w):
    from qgis.gui import QgsFileWidget

    p = w.parent()
    while p is not None:
        if isinstance(p, QgsFileWidget):
            return True
        p = p.parent()
    return False


def test_settings_round_trip(plugin_pkg, clean_settings, tmp_path):
    from DocQGISProject.gui.dialog import DocumentDialog

    a = DocumentDialog(FakeIface())
    a.rb_file.setChecked(True)
    a.project_file.setFilePath("/x/y.qgz")
    a.out_folder.setFilePath(str(tmp_path))
    a.fmt_boxes["pdf"].setChecked(False)
    a._select(a.detail, "full")
    a.dpi.setValue(200)
    a.redact.setChecked(False)
    a.embed.setChecked(False)
    a._select(a.shots, "all")
    a.reject()  # closing saves
    b = DocumentDialog(FakeIface())
    assert b.rb_file.isChecked() and b.project_file.filePath() == "/x/y.qgz"
    assert b.out_folder.filePath() == str(tmp_path)
    assert not b.fmt_boxes["pdf"].isChecked() and b.fmt_boxes["json"].isChecked()
    assert b.detail.currentData() == "full" and b.dpi.value() == 200
    assert not b.redact.isChecked() and not b.embed.isChecked()
    assert b.shots.currentData() == "all"
    o = b.options().validate()
    assert o.screenshots == "none"  # a project file: screenshots are not possible
    assert o.formats == ("json", "markdown", "html") and not o.redact


def test_dialog_run_on_a_file(dialog, fixtures_dir, tmp_path):
    dialog.rb_file.setChecked(True)
    dialog.project_file.setFilePath(str(fixtures_dir / "layout.qgz"))
    dialog.out_folder.setFilePath(str(tmp_path))
    for f, box in dialog.fmt_boxes.items():
        box.setChecked(f in ("json", "markdown"))
    dialog.images.setChecked(False)
    dialog._update_state()
    assert dialog.btn_run.isEnabled()
    dialog.run()
    assert "Wrote" in dialog.status.text() and "%" in dialog.status.text()
    assert (tmp_path / "report.md").is_file() and (tmp_path / "project.json").is_file()
    assert dialog.btn_open.isEnabled() and dialog._report_path().endswith("report.md")
    assert dialog.btn_run.isEnabled() and not dialog.btn_cancel.isEnabled()


def test_dialog_reports_cancel_and_failure(dialog, fixtures_dir, tmp_path, monkeypatch):
    import DocQGISProject.core.runner as runner

    dialog.rb_file.setChecked(True)
    dialog.project_file.setFilePath(str(fixtures_dir / "basic.qgz"))
    dialog.out_folder.setFilePath(str(tmp_path))

    def cancelled(*a, **k):
        raise runner.Cancelled()

    monkeypatch.setattr(runner, "document_project", cancelled)
    dialog.run()
    assert "Cancelled" in dialog.status.text()

    def broken(*a, **k):
        raise ValueError("password='hunter2' broke it")  # pragma: allowlist secret

    monkeypatch.setattr(runner, "document_project", broken)
    dialog.run()
    assert "failed" in dialog.status.text() and "hunter2" not in dialog.status.text()
    assert not dialog.running and dialog.btn_close.isEnabled()


def test_closing_mid_run_cancels(dialog):
    from qgis.core import QgsFeedback

    dialog.running = True
    dialog.feedback = QgsFeedback()
    dialog.reject()
    assert dialog.feedback.isCanceled()
    dialog.running = False
    dialog.feedback = None


def test_layer_list_and_screenshot_controls(dialog, live_layout_project):
    dialog._fill_layers()
    assert dialog.layer_list.count() == len(live_layout_project.mapLayers())
    dialog.rb_open.setChecked(True)
    dialog.images.setChecked(True)
    dialog._select(dialog.shots, "layers")
    dialog._update_state()
    assert dialog.layer_list.isEnabled()
    from qgis.PyQt.QtCore import Qt

    dialog.layer_list.item(0).setCheckState(Qt.CheckState.Checked)
    o = dialog.options().validate()
    assert o.screenshots == "layers" and len(o.screenshot_layers) == 1
    dialog.images.setChecked(False)
    assert not dialog.shots.isEnabled() and dialog.options().validate().screenshots == "none"


def test_uninspectable_view_is_blacked_out(qgis_app, plugin_pkg, monkeypatch):
    """Fail closed: a list the masking cannot read is covered whole."""
    from qgis.PyQt.QtWidgets import QListWidget, QVBoxLayout, QWidget

    import DocQGISProject.gui.screenshots as shots

    w = QWidget()
    lst = QListWidget()
    lst.addItems(["anything"])
    QVBoxLayout(w).addWidget(lst)
    w.resize(300, 150)
    w.show()

    def broken(view, root):
        raise RuntimeError("protected")

    monkeypatch.setattr(shots, "_view_rects", broken)
    image, masked = shots.grab_masked(w)
    assert masked == 1
    ratio = image.devicePixelRatio() or 1.0
    c = lst.geometry().center()
    assert image.pixelColor(int(c.x() * ratio), int(c.y() * ratio)).getRgb()[:3] == (40, 40, 40)
    w.close()

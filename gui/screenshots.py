# SPDX-License-Identifier: GPL-2.0-or-later
"""Dialog screenshots (docs/DESIGN.md section 6b). GUI runs only, opt-in, best effort.

How: each QGIS dialog is opened through the QGIS interface, which shows it modally (and blocks,
except raster Layer Properties, which QGIS shows modally with show() and returns at once).
A timer armed just before the call finds the new modal dialog, steps through its pages, grabs
each one with QWidget.grab() (the widget only, never the desktop), and closes it with reject()
so nothing is applied. The reject is in a `finally`: an error can never leave QGIS stuck behind
an open modal dialog.

Privacy (design section 9):
- pages that list data sources, connection details or logins are skipped by title;
- before each grab, every visible text field that shows a path, URL or login is painted over;
- the report says what was skipped and how many fields were masked.

Layout designer item panels are fragile across QGIS versions: they are tried, and a failure
becomes a note, never an error.
"""

import platform
import re

from qgis.core import Qgis, QgsApplication, QgsLayoutItem, QgsLayoutItemPage, QgsSettings
from qgis.PyQt.QtCore import QCoreApplication, QElapsedTimer, QModelIndex, QPoint, QRect, QSize, QTimer
from qgis.PyQt.QtGui import QColor, QPainter
from qgis.PyQt.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QHeaderView,
    QApplication,
    QComboBox,
    QDockWidget,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QStackedWidget,
    QTextEdit,
)

from ..core.safe_paths import sanitize_name

# Page titles never grabbed (lower case, matched as substrings): they show sources or logins.
SKIP_PAGES = ("source", "information", "server", "auth", "connection", "credential", "password")
SKIP_REASON = "the page shows data sources, addresses or logins"
# Text that is masked wherever it appears in a field.
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(://|^[a-z]:[\\/]|^/|^\\\\|^\.{1,2}[\\/]|[\\/].+[\\/]|dbname=|host=|user(name)?=|password|authcfg|"
    r"service=|token|api[_-]?key|\.(gpkg|shp|tif|tiff|qgz|qgs|svg|png|csv|sqlite|gdb)\b)"
)
TEXT_WIDGETS = (QLineEdit, QPlainTextEdit, QTextEdit, QLabel, QComboBox, QAbstractButton)
MAX_PAGES = 60
MAX_VIEW_CELLS = 20000
MAX_LAYOUT_ITEMS = 30
MODAL_WAIT_MS = 5000


def _process_events(ms=30):
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        QCoreApplication.processEvents()


def _widget_text(w):
    if isinstance(w, QLineEdit):
        return w.text()
    if isinstance(w, (QPlainTextEdit,)):
        return w.toPlainText()
    if isinstance(w, QTextEdit):
        return w.toPlainText()
    if isinstance(w, QComboBox):
        return w.currentText()
    if isinstance(w, (QLabel, QAbstractButton)):
        return w.text()
    return ""


def _sensitive(text):
    """A path, URL or login, or a name that says it holds a secret (service_token, api_key)."""
    from ..core.redact import secret_name_kind, sensitive_kind

    for line in (text or "").splitlines()[:200]:
        line = line.strip()
        if line and (SENSITIVE_TEXT_RE.search(line) or sensitive_kind(line) or secret_name_kind(line)):
            return True
    return False


def _columns(model, parent):
    """Column count; list models (QListWidget) make columnCount private in PyQt6: one column."""
    try:
        return max(1, model.columnCount(parent))
    except TypeError:
        return 1


def _view_rects(view, root):
    """Rows of a list, tree or table view that show anything sensitive. The whole row is masked,
    so a secret value next to its name (a variable, an action) is covered too."""
    model = view.model()
    if model is None:
        return []
    rects, budget = [], [MAX_VIEW_CELLS]

    def walk(parent, depth):
        for row in range(model.rowCount(parent)):
            if budget[0] <= 0:
                return
            cols = _columns(model, parent)
            budget[0] -= cols
            indexes = [model.index(row, c, parent) for c in range(cols)]
            if any(_sensitive(str(ix.data() or "")) for ix in indexes):
                row_rect = QRect()
                for ix in indexes:
                    r = view.visualRect(ix)
                    if r.isValid():
                        row_rect = row_rect.united(r)
                if row_rect.isValid():
                    # The full width of the visible area, at the row's height (viewport -> root).
                    vp = view.viewport()
                    top_left = vp.mapTo(root, QPoint(0, row_rect.top()))
                    rects.append(QRect(top_left, QSize(vp.width(), row_rect.height())))
            if depth < 4 and model.rowCount(indexes[0]) > 0:  # hasChildren() is private on list models
                walk(indexes[0], depth + 1)

    walk(QModelIndex(), 0)
    return rects


def _sensitive_rects(root):
    """Rectangles (in root coordinates) of visible widgets showing a path, URL or login."""
    rects = []
    for view in root.findChildren(QAbstractItemView):
        if isinstance(view, QHeaderView) or not view.isVisibleTo(root):
            continue  # headers show column titles, not data
        try:
            rects += _view_rects(view, root)
        except (RuntimeError, TypeError):
            # A view this code cannot inspect is blacked out whole: fail closed, never leak.
            rects.append(QRect(view.mapTo(root, QPoint(0, 0)), view.size()))
    for cls in TEXT_WIDGETS:
        for w in root.findChildren(cls):
            if not w.isVisibleTo(root):
                continue
            if not _sensitive(_widget_text(w) or ""):
                continue
            top_left = w.mapTo(root, QPoint(0, 0))
            rects.append(QRect(top_left, w.size()))
    return rects


def grab_masked(widget):
    """Grab a widget as a QImage with sensitive fields painted over. Returns (image, masked_count)."""
    rects = _sensitive_rects(widget)
    pixmap = widget.grab()
    image = pixmap.toImage()
    if rects:
        ratio = pixmap.devicePixelRatio() or 1.0
        painter = QPainter(image)
        try:
            for r in rects:
                painter.fillRect(
                    QRect(int(r.x() * ratio), int(r.y() * ratio), int(r.width() * ratio), int(r.height() * ratio)),
                    QColor(40, 40, 40),
                )
        finally:
            painter.end()
    return image, len(rects)


def _skip_page(title):
    t = (title or "").lower()
    return any(word in t for word in SKIP_PAGES)


def _options_pages(dialog):
    """(list widget, stacked widget) of a QgsOptionsDialogBase-style dialog, or (None, None)."""
    lst = dialog.findChild(QListWidget, "mOptionsListWidget")
    stack = dialog.findChild(QStackedWidget, "mOptionsStackedWidget")
    return lst, stack


def grab_modal(open_fn, handle_fn):
    """Call open_fn() (which shows a modal dialog and blocks); handle_fn(dialog) runs while it is
    open. The dialog is always rejected afterwards. Returns handle_fn's result, or None if no new
    modal dialog appeared."""
    before = QApplication.activeModalWidget()
    state = {"result": None, "found": False, "error": None}
    clock = QElapsedTimer()
    clock.start()

    def poll():
        dialog = QApplication.activeModalWidget()
        if dialog is None or dialog is before:
            if clock.elapsed() < MODAL_WAIT_MS:
                QTimer.singleShot(50, poll)
            return
        state["found"] = True
        try:
            _process_events(100)  # let the dialog lay itself out
            state["result"] = handle_fn(dialog)
        except Exception as exc:  # reported by the caller; the dialog must still close
            state["error"] = exc
        finally:
            dialog.reject()

    QTimer.singleShot(0, poll)
    open_fn()
    # Most QGIS dialogs block in exec() until closed, so the poll has already run by now. A raster
    # Layer Properties dialog is modal but shown with show(), and open_fn returns at once: keep
    # the events flowing until the poll has found and closed it, or the wait limit has passed.
    while not state["found"] and clock.elapsed() < MODAL_WAIT_MS + 500:
        _process_events(50)
    if state["error"] is not None:
        raise state["error"]
    return state["result"]


class Screenshotter:
    """Callable passed to core.runner.document_project(screenshotter=...)."""

    def __init__(self, iface):
        self.iface = iface

    # The runner calls this as a collection step.
    def __call__(self, project, model, options, sink, feedback):
        if project is not self._live_project():
            model.add_problem(
                "info", "screenshots", "Dialog screenshots are only taken of the open project, not of a project file."
            )
            return None
        self.items = []
        self.sink, self.feedback, self.model = sink, feedback, model
        model.screenshots = {"environment": self._environment(), "items": self.items}
        if self._project_dialog() is False:
            return False
        layers = []
        if options.screenshots in ("layers", "all"):
            wanted = set(options.screenshot_layers) if options.screenshots == "layers" else None
            layers = [lyr for lyr in project.mapLayers().values() if wanted is None or lyr.id() in wanted]
            missing = (wanted or set()) - {lyr.id() for lyr in layers}
            if missing:
                model.add_problem("warning", "screenshots", f"{len(missing)} chosen layers are not in the project.")
        for n, layer in enumerate(sorted(layers, key=lambda lyr: lyr.name().lower()), 1):
            if self._cancelled():
                return False
            if self._layer_dialog(layer, n) is False:
                return False
        for n, layout in enumerate(project.layoutManager().printLayouts(), 1):
            if self._cancelled():
                return False
            self._layout_designer(layout, n)
        return None

    @staticmethod
    def _live_project():
        from qgis.core import QgsProject

        return QgsProject.instance()

    def _cancelled(self):
        return self.feedback is not None and self.feedback.isCanceled()

    @staticmethod
    def _environment():
        settings = QgsSettings()
        return {
            "QGIS": Qgis.version(),
            "Qt style": QApplication.style().name() if QApplication.style() else "",
            "QGIS theme": settings.value("UI/UITheme", "default"),
            "Operating system": f"{platform.system()} {platform.release()}",
            "Locale": QgsApplication.locale(),
            "Screen scale": str(getattr(QApplication.primaryScreen(), "devicePixelRatio", lambda: 1.0)()),
        }

    def _add(self, kind, target, target_id, page, image=None, skipped=None, masked=0):
        self.items.append({
            "kind": kind,
            "target": target,
            "target_id": target_id,
            "page": page,
            "image": image,
            "skipped": skipped,
            "masked": masked,
        })

    def _grab_pages(self, dialog, kind, target, target_id, prefix):
        lst, stack = _options_pages(dialog)
        if lst is None or stack is None:
            image, masked = grab_masked(dialog)
            name = self.sink.add_png(f"images/screenshots/{prefix}_01.png", image)
            self._add(kind, target, target_id, "Dialog", name, None if name else "the image budget was reached", masked)
            return None
        for row in range(min(lst.count(), MAX_PAGES)):
            if self._cancelled():
                return False
            item = lst.item(row)
            title = item.text() if item is not None else f"Page {row + 1}"
            if item is None or item.isHidden():
                continue
            if _skip_page(title):
                self._add(kind, target, target_id, title, skipped=SKIP_REASON)
                continue
            lst.setCurrentRow(row)
            _process_events(60)
            image, masked = grab_masked(dialog)
            name = self.sink.add_png(f"images/screenshots/{prefix}_{row + 1:02d}.png", image)
            self._add(kind, target, target_id, title, name, None if name else "the image budget was reached", masked)
        return None

    def _project_dialog(self):
        def handle(dialog):
            return self._grab_pages(dialog, "project", "project", None, "project")

        try:
            result = grab_modal(lambda: self.iface.showProjectPropertiesDialog(""), handle)
        except Exception as exc:  # best effort: a note, never a failed run
            self._add(
                "project", "project", None, "Project Properties", skipped=f"the dialog failed ({type(exc).__name__})"
            )
            return None
        if result is None and not any(i["kind"] == "project" for i in self.items):
            self._add("project", "project", None, "Project Properties", skipped="the dialog did not open")
        return result

    def _layer_dialog(self, layer, n):
        prefix = f"layer_{n:03d}_{sanitize_name(layer.name())[:40]}"

        def handle(dialog):
            return self._grab_pages(dialog, "layer", layer.name(), layer.id(), prefix)

        try:
            result = grab_modal(lambda: self.iface.showLayerProperties(layer, ""), handle)
        except Exception as exc:
            self._add(
                "layer",
                layer.name(),
                layer.id(),
                "Layer Properties",
                skipped=f"the dialog failed ({type(exc).__name__})",
            )
            return None
        if result is None and not any(i["target_id"] == layer.id() for i in self.items):
            self._add("layer", layer.name(), layer.id(), "Layer Properties", skipped="the dialog did not open")
        return result

    def _layout_designer(self, layout, n):
        """The designer window, then the item properties panel for each item (best effort)."""
        prefix = f"layout_{n:02d}_{sanitize_name(layout.name())[:40]}"
        designer = None
        try:
            designer = self.iface.openLayoutDesigner(layout)
            if designer is None:
                self._add("layout", layout.name(), None, "Layout Designer", skipped="the designer did not open")
                return
            window = designer.window()
            _process_events(200)
            image, masked = grab_masked(window)
            name = self.sink.add_png(f"images/screenshots/{prefix}_00.png", image)
            self._add("layout", layout.name(), None, "Layout Designer", name, None if name else "image budget", masked)
            dock = next((d for d in window.findChildren(QDockWidget) if d.objectName() == "ItemDock"), None)
            if dock is None:
                self._add("layout", layout.name(), None, "Item properties", skipped="the item panel was not found")
                return
            items = [
                it for it in layout.items() if isinstance(it, QgsLayoutItem) and not isinstance(it, QgsLayoutItemPage)
            ][:MAX_LAYOUT_ITEMS]
            for k, item in enumerate(items, 1):
                if self._cancelled():
                    return
                label = item.displayName() if hasattr(item, "displayName") else f"Item {k}"
                try:
                    designer.selectItems([item])
                    dock.show()
                    _process_events(80)
                    image, masked = grab_masked(dock)
                except Exception as exc:
                    self._add("layout", layout.name(), None, f"Item: {label}", skipped=f"failed ({type(exc).__name__})")
                    continue
                name = self.sink.add_png(f"images/screenshots/{prefix}_{k:02d}.png", image)
                self._add(
                    "layout", layout.name(), None, f"Item: {label}", name, None if name else "image budget", masked
                )
        except Exception as exc:
            self._add("layout", layout.name(), None, "Layout Designer", skipped=f"failed ({type(exc).__name__})")
        finally:
            if designer is not None:
                try:
                    designer.close()
                except Exception:  # nosec B110 - closing is best effort; the run goes on
                    pass

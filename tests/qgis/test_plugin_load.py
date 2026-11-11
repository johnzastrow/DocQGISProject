"""The plugin loads, adds its Project-menu action and Processing provider, and unloads cleanly."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class _MessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, title, text, level=None, duration=None):  # noqa: N802
        self.messages.append((title, text))


class _StubIface:
    """The few QgisInterface methods the plugin uses."""

    def __init__(self):
        from qgis.PyQt.QtWidgets import QMainWindow, QMenu

        self._main = QMainWindow()
        self._project_menu = QMenu("Project", self._main)
        self._bar = _MessageBar()

    def mainWindow(self):  # noqa: N802
        return self._main

    def projectMenu(self):  # noqa: N802
        return self._project_menu

    def messageBar(self):  # noqa: N802
        return self._bar


def _import_plugin():
    # Import the repo root as package "DocQGISProject" (the name it has once installed).
    spec = importlib.util.spec_from_file_location(
        "DocQGISProject", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["DocQGISProject"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_load_menu_provider_unload(qgis_app):
    from qgis.core import QgsApplication

    pkg = _import_plugin()
    iface = _StubIface()
    plugin = pkg.classFactory(iface)
    plugin.initProcessing()  # as QGIS does for hasProcessingProvider=yes
    plugin.initGui()

    registry = QgsApplication.processingRegistry()
    provider = registry.providerById("docqgisproject")
    assert provider is not None
    assert provider.name() == "Documentation"

    actions = [a for a in iface.projectMenu().actions() if a.objectName() == "DocQGISProjectDocumentAction"]
    assert len(actions) == 1
    assert actions[0].toolTip()
    assert not actions[0].icon().isNull()

    actions[0].trigger()
    assert iface.messageBar().messages, "menu action should report its placeholder status"

    plugin.unload()
    assert registry.providerById("docqgisproject") is None
    assert not [a for a in iface.projectMenu().actions() if a.objectName() == "DocQGISProjectDocumentAction"]

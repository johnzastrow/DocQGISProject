"""The plugin loads, adds its Project-menu action and Processing provider, and unloads cleanly."""


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


def test_load_menu_provider_unload(qgis_app, plugin_pkg):
    from qgis.core import QgsApplication

    pkg = plugin_pkg
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

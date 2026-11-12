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
        from qgis.PyQt.QtWidgets import QToolBar

        self._project_menu = QMenu("Project", self._main)
        self._toolbar = QToolBar("Project Toolbar", self._main)
        self._plugin_menus = {}
        self._bar = _MessageBar()

    def fileToolBar(self):  # noqa: N802
        return self._toolbar

    def addPluginToMenu(self, name, action):  # noqa: N802
        self._plugin_menus.setdefault(name, []).append(action)

    def removePluginMenu(self, name, action):  # noqa: N802
        self._plugin_menus.get(name, []).remove(action)

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
    # The same action is a Project-toolbar button and a Plugins-menu entry.
    assert actions[0] in iface.fileToolBar().actions()
    assert iface._plugin_menus.get("&DocQGISProject") == [actions[0]]
    assert actions[0].toolTip()
    assert not actions[0].icon().isNull()

    from DocQGISProject.gui import dialog as dialog_mod

    opened = []
    original = dialog_mod.DocumentDialog.exec
    dialog_mod.DocumentDialog.exec = lambda self: opened.append(self.windowTitle()) or 0
    try:
        actions[0].trigger()
    finally:
        dialog_mod.DocumentDialog.exec = original
    assert opened == ["Document Project"], "the menu action opens the dialog"

    plugin.unload()
    assert registry.providerById("docqgisproject") is None
    assert not [a for a in iface.projectMenu().actions() if a.objectName() == "DocQGISProjectDocumentAction"]
    assert not iface.fileToolBar().actions() and not iface._plugin_menus["&DocQGISProject"]

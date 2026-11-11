# SPDX-License-Identifier: GPL-2.0-or-later
"""Plugin class: Project menu entry and Processing provider registration."""

import os

from qgis.core import Qgis, QgsApplication
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .processing_provider.provider import DocQGISProjectProvider

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(PLUGIN_DIR, "icons", "icon.svg")


def tr(text):
    """Translate a user-visible string in the plugin's context."""
    return QCoreApplication.translate("DocQGISProject", text)


class DocQGISProjectPlugin:
    """Registers the menu action and the Processing provider; owns nothing else."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.provider = None

    # QGIS calls initProcessing() for plugins with hasProcessingProvider=yes
    # (also in qgis_process, where there is no GUI). initGui() calls it too, so
    # it must be idempotent.
    def initProcessing(self):  # noqa: N802 - QGIS API name
        if self.provider is None:
            self.provider = DocQGISProjectProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):  # noqa: N802 - QGIS API name
        self.initProcessing()
        self.action = QAction(QIcon(ICON_PATH), tr("Document Project..."), self.iface.mainWindow())
        self.action.setObjectName("DocQGISProjectDocumentAction")
        self.action.setToolTip(
            tr("Write a report (Markdown, HTML, PDF) and a rebuild-grade JSON file describing this project")
        )
        self.action.setStatusTip(self.action.toolTip())
        self.action.triggered.connect(self.run)
        self.iface.projectMenu().addAction(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.projectMenu().removeAction(self.action)
            self.action.deleteLater()
            self.action = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def run(self):
        # Placeholder until the dialog lands (phase P6 of docs/DESIGN.md).
        self.iface.messageBar().pushMessage(
            "DocQGISProject",
            tr("Development build: the documentation engine is not implemented yet."),
            level=Qgis.MessageLevel.Info,
            duration=5,
        )

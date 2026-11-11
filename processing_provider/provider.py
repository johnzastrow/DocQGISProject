# SPDX-License-Identifier: GPL-2.0-or-later
"""Processing provider "Documentation" (docs/DESIGN.md section 7)."""

import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons", "icon.svg")


class DocQGISProjectProvider(QgsProcessingProvider):
    """Provider id 'docqgisproject'; algorithm ids become docqgisproject:<name>."""

    def id(self):
        return "docqgisproject"

    def name(self):
        return "Documentation"

    def longName(self):  # noqa: N802 - QGIS API name
        return "DocQGISProject: project documentation"

    def icon(self):
        return QIcon(ICON_PATH)

    def svgIconPath(self):  # noqa: N802 - QGIS API name
        return ICON_PATH

    def loadAlgorithms(self):  # noqa: N802 - QGIS API name
        from .algorithms import DocumentProjectAlgorithm, RebuildProjectAlgorithm

        self.addAlgorithm(DocumentProjectAlgorithm())
        self.addAlgorithm(RebuildProjectAlgorithm())

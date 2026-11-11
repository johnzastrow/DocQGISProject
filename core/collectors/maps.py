# SPDX-License-Identifier: GPL-2.0-or-later
"""Map images rendered by QGIS: a thumbnail per layer and a project overview map.

Only layers whose data are loaded are drawn, so web and database layers appear only when the
user opted in (include_network_layers); an unreachable server can never be contacted here.
"""

from qgis.core import QgsMapRendererSequentialJob, QgsMapSettings, QgsRectangle
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

THUMB_PX = 360
OVERVIEW_PX = 900


def _render(layers, crs, extent, width_px, project, dpi):
    if not layers or extent is None or extent.isEmpty():
        return None
    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setDestinationCrs(crs)
    settings.setTransformContext(project.transformContext())
    settings.setBackgroundColor(QColor("#ffffff"))
    settings.setOutputDpi(dpi)
    ratio = extent.height() / extent.width() if extent.width() else 1.0
    settings.setOutputSize(QSize(width_px, max(40, min(width_px * 2, int(width_px * ratio)))))
    settings.setExtent(extent)
    job = QgsMapRendererSequentialJob(settings)
    job.start()
    job.waitForFinished()
    return job.renderedImage()


def layer_thumbnail(layer, project, dpi):
    """The layer alone, at its own extent, in its own CRS."""
    if not layer.isValid():
        return None
    extent = QgsRectangle(layer.extent())
    if extent.isEmpty():
        return None
    extent.scale(1.05)
    return _render([layer], layer.crs(), extent, THUMB_PX, project, dpi)


def project_overview(project, dpi):
    """Visible, loaded layers in layer-tree order at the project's full extent."""
    layers = [lyr for lyr in project.layerTreeRoot().checkedLayers() if lyr is not None and lyr.isValid()]
    if not layers:
        return None
    extent = project.viewSettings().fullExtent()
    if extent.isEmpty():
        return None
    extent = QgsRectangle(extent)
    extent.scale(1.05)
    return _render(layers, project.crs(), extent, OVERVIEW_PX, project, dpi)

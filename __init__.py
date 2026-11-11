# SPDX-License-Identifier: GPL-2.0-or-later
"""DocQGISProject: document a QGIS project for people and machines."""


def classFactory(iface):  # noqa: N802 - name required by QGIS
    """Entry point called by QGIS when the plugin is loaded."""
    from .docqgisproject import DocQGISProjectPlugin

    return DocQGISProjectPlugin(iface)

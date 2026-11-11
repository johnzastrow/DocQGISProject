# SPDX-License-Identifier: GPL-2.0-or-later
"""QGIS user-interface names, so every setting in a report says where to find it in QGIS.

Wording follows the QGIS 4 English interface. Keep entries short: they fill a table cell.
"""

WHERE = {
    # Project Properties
    "project_title": "Project > Properties > General > Project title",
    "project_home": "Project > Properties > General > Project home",
    "path_storage": "Project > Properties > General > Save paths",
    "background_color": "Project > Properties > General > Background color",
    "selection_color": "Project > Properties > General > Selection color",
    "ellipsoid": "Project > Properties > General > Measurements > Ellipsoid",
    "distance_units": "Project > Properties > General > Measurements > Units for distance measurement",
    "area_units": "Project > Properties > General > Measurements > Units for area measurement",
    "project_crs": "Project > Properties > CRS",
    "transformations": "Project > Properties > Transformations",
    "view_extent": "Project > Properties > View Settings > Set project full extent",
    "project_metadata": "Project > Properties > Metadata",
    "variables": "Project > Properties > Variables",
    "relations": "Project > Properties > Relations",
    "macros": "Project > Properties > Macros",
    "themes": "Layers panel > Manage Map Themes (eye icon)",
    "bookmarks": "View > Panels > Spatial Bookmarks",
    # Layer Properties
    "layer_name": "Layer Properties > Source > Layer name",
    "layer_crs": "Layer Properties > Source > Assigned Coordinate Reference System",
    "subset": "Layer Properties > Source > Provider Feature Filter (Query Builder)",
    "layer_info": "Layer Properties > Information",
    "scale_visibility": "Layer Properties > Rendering > Scale Dependent Visibility",
    "opacity": "Layer Properties > Symbology > Layer Rendering > Opacity",
    "blend_mode": "Layer Properties > Symbology > Layer Rendering > Blending mode",
    "fields": "Layer Properties > Fields",
    "virtual_field": "Layer Properties > Fields > Field Calculator (virtual field)",
    "widgets": "Layer Properties > Attributes Form",
    "joins": "Layer Properties > Joins",
    "layer_metadata": "Layer Properties > Metadata",
    "notes": "Layers panel > right-click the layer > Edit Layer Notes",
    "tree_group": "Layers panel > Add Group",
    "exclusive_group": "Layers panel > right-click the group > Mutually Exclusive Group",
}

# How to add a layer of each provider in QGIS (Data Source Manager = Layer > Data Source Manager).
ADD_LAYER = {
    "ogr": "Layer > Add Layer > Add Vector Layer",
    "gdal": "Layer > Add Layer > Add Raster Layer",
    "postgres": "Data Source Manager > PostgreSQL",
    "postgresraster": "Data Source Manager > PostgreSQL",
    "spatialite": "Data Source Manager > SpatiaLite",
    "delimitedtext": "Data Source Manager > Delimited Text",
    "memory": "Layer > Create Layer > New Temporary Scratch Layer",
    "virtual": "Data Source Manager > Virtual Layer",
    "wfs": "Data Source Manager > WFS / OGC API - Features",
    "oapif": "Data Source Manager > WFS / OGC API - Features",
    "wcs": "Data Source Manager > WCS",
    "arcgismapserver": "Data Source Manager > ArcGIS REST Server",
    "arcgisfeatureserver": "Data Source Manager > ArcGIS REST Server",
    "mssql": "Data Source Manager > MS SQL Server",
    "oracle": "Data Source Manager > Oracle",
    "hana": "Data Source Manager > SAP HANA",
    "vectortile": "Data Source Manager > Vector Tile",
    "mdal": "Data Source Manager > Mesh",
    "pdal": "Data Source Manager > Point Cloud",
    "copc": "Data Source Manager > Point Cloud",
    "ept": "Data Source Manager > Point Cloud",
}


def add_layer_hint(provider, parts):
    """Menu path for adding a layer with this provider; XYZ tiles use the wms provider."""
    if provider == "wms":
        if isinstance(parts, dict) and parts.get("type") == "xyz":
            return "Data Source Manager > XYZ"
        return "Data Source Manager > WMS/WMTS"
    return ADD_LAYER.get(provider, f"Data Source Manager (provider '{provider}')")

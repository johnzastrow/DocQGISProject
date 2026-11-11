"""Generate small synthetic QGIS projects used as test fixtures.

Run under QGIS's own Python (Ubuntu example):

    PATH=/usr/bin:/bin QT_QPA_PLATFORM=offscreen /usr/bin/python3 -I \
        tests/fixtures/make_fixtures.py --out tests/fixtures/generated

Writes one GeoPackage of data plus these projects (paths stored relative):

    basic.qgz    groups (one mutually exclusive), variables, bookmarks, project metadata,
                 a relation, two map themes
    styling.qgz  one layer per renderer type (single, categorized, graduated, rule-based,
                 inverted polygon, 2.5D, point cluster, point displacement, heatmap, null),
                 multi-layer symbols, a data-defined property, a paint effect,
                 simple and rule-based labeling
    layout.qgz   a print layout with each common item type (map with grid and overview,
                 legend, scale bar, label, picture, shape, polygon and polyline nodes,
                 marker, attribute table, manual table), an atlas layout and a report

Output is deterministic (no randomness). Nothing is fetched from the network.
"""

import argparse
import shutil
import sys
from pathlib import Path

QGIS_PYTHON = "/usr/share/qgis/python"
if QGIS_PYTHON not in sys.path:
    sys.path.insert(0, QGIS_PYTHON)

from qgis.core import (  # noqa: E402
    Qgis,
    Qgs25DRenderer,
    QgsApplication,
    QgsBookmark,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsDropShadowEffect,
    QgsEffectStack,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsGraduatedSymbolRenderer,
    QgsHeatmapRenderer,
    QgsInvertedPolygonRenderer,
    QgsLayoutExporter,
    QgsLayoutFrame,
    QgsLayoutItemAttributeTable,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemManualTable,
    QgsLayoutItemMap,
    QgsLayoutItemMapGrid,
    QgsLayoutItemMapOverview,
    QgsLayoutItemMarker,
    QgsLayoutItemPicture,
    QgsLayoutItemPolygon,
    QgsLayoutItemPolyline,
    QgsLayoutItemScaleBar,
    QgsLayoutItemShape,
    QgsLayoutMeasurement,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLineSymbol,
    QgsMapThemeCollection,
    QgsMarkerLineSymbolLayer,
    QgsMarkerSymbol,
    QgsNullSymbolRenderer,
    QgsPalLayerSettings,
    QgsPointClusterRenderer,
    QgsPointDisplacementRenderer,
    QgsPointXY,
    QgsPrintLayout,
    QgsProject,
    QgsProperty,
    QgsReferencedRectangle,
    QgsRelation,
    QgsRelationContext,
    QgsRendererCategory,
    QgsRendererRange,
    QgsReport,
    QgsReportSectionFieldGroup,
    QgsRuleBasedLabeling,
    QgsRuleBasedRenderer,
    QgsSimpleLineSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsSymbolLayer,
    QgsTableCell,
    QgsTextFormat,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QPointF, QRectF  # noqa: E402
from qgis.PyQt.QtGui import QColor, QPolygonF  # noqa: E402

CRS = "EPSG:32619"  # WGS 84 / UTM zone 19N (Maine); metres
X0, Y0, CELL = 400000.0, 4900000.0, 1000.0  # 3 x 3 grid of 1 km cells
REPO_ICON = Path(__file__).resolve().parents[2] / "icons" / "icon.svg"


# --------------------------------------------------------------------------- data


def _memory_layer(uri, name, rows):
    layer = QgsVectorLayer(uri, name, "memory")
    feats = []
    for geom_wkt, attrs in rows:
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromWkt(geom_wkt))
        f.setAttributes(attrs)
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    return layer


def _zones():
    rows = []
    for i in range(9):
        r, c = divmod(i, 3)
        x, y = X0 + c * CELL, Y0 + r * CELL
        wkt = f"POLYGON(({x} {y},{x + CELL} {y},{x + CELL} {y + CELL},{x} {y + CELL},{x} {y}))"
        rows.append((wkt, [i + 1, f"Zone {i + 1}", "ABC"[i % 3], 100.0 + 10 * i]))
    return _memory_layer(
        f"Polygon?crs={CRS}&field=id:integer&field=name:string(30)&field=zone:string(1)&field=area_ha:double",
        "zones",
        rows,
    )


def _sites():
    rows = []
    for i in range(20):
        # Deterministic scatter inside the grid; two pairs coincide to exercise clustering.
        x = X0 + 150 + (i * 337) % 2700
        y = Y0 + 150 + (i * 571) % 2700
        if i in (5, 6):
            x, y = X0 + 1500, Y0 + 1500
        zone_id = int((y - Y0) // CELL) * 3 + int((x - X0) // CELL) + 1
        rows.append((f"POINT({x} {y})", [i + 1, zone_id, ["well", "spring", "gauge"][i % 3], float(i * 5)]))
    return _memory_layer(
        f"Point?crs={CRS}&field=id:integer&field=zone_id:integer&field=kind:string(10)&field=value:double",
        "sites",
        rows,
    )


def _trails():
    rows = [
        (f"LINESTRING({X0} {Y0 + 500},{X0 + 1500} {Y0 + 1200},{X0 + 3000} {Y0 + 900})", [1, "Ridge Trail", "major"]),
        (f"LINESTRING({X0 + 400} {Y0},{X0 + 700} {Y0 + 1600},{X0 + 600} {Y0 + 3000})", [2, "Brook Path", "minor"]),
        (f"LINESTRING({X0 + 2000} {Y0 + 3000},{X0 + 2500} {Y0 + 1500})", [3, "Spur", "minor"]),
    ]
    return _memory_layer(
        f"LineString?crs={CRS}&field=id:integer&field=name:string(30)&field=class:string(10)",
        "trails",
        rows,
    )


def write_data(gpkg):
    """Write the three tables into one GeoPackage."""
    if gpkg.exists():
        gpkg.unlink()
    ctx = QgsProject.instance().transformContext()
    for i, layer in enumerate((_zones(), _sites(), _trails())):
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = layer.name()
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
            if i == 0
            else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        )
        err, msg, _path, _lyr = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(gpkg), ctx, opts)
        if err != QgsVectorFileWriter.WriterError.NoError:
            raise RuntimeError(f"writing {layer.name()}: {msg}")


def load(gpkg, table, name=None):
    layer = QgsVectorLayer(f"{gpkg}|layername={table}", name or table, "ogr")
    if not layer.isValid():
        raise RuntimeError(f"cannot open {gpkg}|{table}")
    return layer


def new_project(title):
    project = QgsProject()
    project.setCrs(QgsCoordinateReferenceSystem(CRS))
    project.setTitle(title)
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    return project


# --------------------------------------------------------------------------- projects


def make_basic(out, gpkg):
    project = new_project("Fixture: basic")
    zones, sites, trails = load(gpkg, "zones"), load(gpkg, "sites"), load(gpkg, "trails")
    for lyr in (zones, sites, trails):
        project.addMapLayer(lyr, False)

    root = project.layerTreeRoot()
    base = root.addGroup("Base")
    base.addLayer(zones)
    features = root.addGroup("Features")
    features.addLayer(sites)
    features.addLayer(trails)
    exclusive = root.addGroup("Alternatives (mutually exclusive)")
    exclusive.setIsMutuallyExclusive(True)
    # Register each layer with the project BEFORE adding it to the tree; otherwise the
    # Python wrapper is the only owner and the layer is garbage-collected.
    for alt in ("zones (alt A)", "zones (alt B)"):
        lyr = load(gpkg, "zones", alt)
        project.addMapLayer(lyr, False)
        exclusive.addLayer(lyr)
    features.setExpanded(False)

    QgsExpressionContextUtils.setProjectVariable(project, "fixture_author", "DocQGISProject tests")
    QgsExpressionContextUtils.setProjectVariable(project, "fixture_revision", "1")

    md = project.metadata()
    md.setTitle("Basic fixture")
    md.setAbstract("Synthetic project for DocQGISProject tests.")
    md.setKeywords({"fixture": ["test", "synthetic"]})
    project.setMetadata(md)

    bm = QgsBookmark()
    bm.setName("Centre cell")
    bm.setGroup("Fixture")
    bm.setExtent(QgsReferencedRectangle(zones.extent().buffered(-CELL), QgsCoordinateReferenceSystem(CRS)))
    project.bookmarkManager().addBookmark(bm)

    rel = QgsRelation(QgsRelationContext(project))
    rel.setId("zones_sites")
    rel.setName("Sites in zone")
    rel.setReferencedLayer(zones.id())
    rel.setReferencingLayer(sites.id())
    rel.addFieldPair("zone_id", "id")
    if not rel.isValid():
        raise RuntimeError(f"relation invalid: {rel.validationError()}")
    project.relationManager().addRelation(rel)

    themes = project.mapThemeCollection()
    themes.insert("All", QgsMapThemeCollection.createThemeFromCurrentState(root, _model(project)))
    trails_node = root.findLayer(trails.id())
    sites_node = root.findLayer(sites.id())
    trails_node.setItemVisibilityChecked(False)
    sites_node.setItemVisibilityChecked(False)
    themes.insert("Zones only", QgsMapThemeCollection.createThemeFromCurrentState(root, _model(project)))
    trails_node.setItemVisibilityChecked(True)
    sites_node.setItemVisibilityChecked(True)

    _write(project, out / "basic.qgz")


def _model(project):
    from qgis.core import QgsLayerTreeModel  # local: only needed for themes

    model = QgsLayerTreeModel(project.layerTreeRoot())
    _model.keep.append(model)  # keep alive while the theme is captured
    return model


_model.keep = []


def _fill(color, outline="#333333"):
    return QgsFillSymbol.createSimple({"color": color, "outline_color": outline, "outline_width": "0.3"})


def _marker(color, size="3"):
    return QgsMarkerSymbol.createSimple({"name": "circle", "color": color, "size": size})


def make_styling(out, gpkg):
    project = new_project("Fixture: styling")
    root = project.layerTreeRoot()

    def add(table, name, renderer=None):
        lyr = load(gpkg, table, name)
        if renderer is not None:
            lyr.setRenderer(renderer)
        project.addMapLayer(lyr)
        return lyr

    # single symbol with a paint effect on the symbol layer
    single = _fill("#9cc58b")
    stack = QgsEffectStack()
    stack.appendEffect(QgsDropShadowEffect())
    single.symbolLayer(0).setPaintEffect(stack)
    add("zones", "single", QgsSingleSymbolRenderer(single))

    # categorized (each category gets its own symbol: never share symbol objects)
    cats = [QgsRendererCategory(z, _fill(c), f"Zone {z}") for z, c in zip("ABC", ("#e0c068", "#8fb8de", "#c98fde"))]
    add("zones", "categorized", QgsCategorizedSymbolRenderer("zone", cats))

    # graduated
    ranges = [
        QgsRendererRange(100, 130, _fill("#fee5d9"), "100 - 130"),
        QgsRendererRange(130, 160, _fill("#fcae91"), "130 - 160"),
        QgsRendererRange(160, 190, _fill("#de2d26"), "160 - 190"),
    ]
    add("zones", "graduated", QgsGraduatedSymbolRenderer("area_ha", ranges))

    # rule-based
    rb_root = QgsRuleBasedRenderer.Rule(None)
    rb_root.appendChild(QgsRuleBasedRenderer.Rule(_fill("#ffd166"), 0, 0, "\"zone\" = 'A'", "Zone A"))
    rb_root.appendChild(QgsRuleBasedRenderer.Rule(_fill("#06d6a0"), 0, 0, "\"area_ha\" > 150", "Large"))
    rb_root.appendChild(QgsRuleBasedRenderer.Rule(_fill("#cccccc"), 0, 0, "ELSE", "Other"))
    add("zones", "rule-based", QgsRuleBasedRenderer(rb_root))

    add("zones", "inverted polygon", QgsInvertedPolygonRenderer(QgsSingleSymbolRenderer(_fill("#00000055"))))
    add("zones", "2.5D", Qgs25DRenderer())

    cluster = QgsPointClusterRenderer()
    cluster.setEmbeddedRenderer(QgsSingleSymbolRenderer(_marker("#b5462f")))
    cluster.setTolerance(5)
    add("sites", "point cluster", cluster)

    disp = QgsPointDisplacementRenderer()
    disp.setEmbeddedRenderer(QgsSingleSymbolRenderer(_marker("#3a5a40")))
    add("sites", "point displacement", disp)

    heat = QgsHeatmapRenderer()
    heat.setRadius(10)
    heat.setWeightExpression("value")
    add("sites", "heatmap", heat)

    add("sites", "null symbol", QgsNullSymbolRenderer())

    # multi-layer line symbol with a data-defined width
    line = QgsLineSymbol()
    line.deleteSymbolLayer(0)
    casing = QgsSimpleLineSymbolLayer(QColor("#333333"), 1.2)
    centre = QgsSimpleLineSymbolLayer(QColor("#f4e285"), 0.6)
    centre.setDataDefinedProperty(
        QgsSymbolLayer.Property.StrokeWidth,
        QgsProperty.fromExpression("CASE WHEN \"class\" = 'major' THEN 0.8 ELSE 0.4 END"),
    )
    markers = QgsMarkerLineSymbolLayer()
    markers.setInterval(10)
    markers.setSubSymbol(_marker("#333333", "1.2"))
    for sl in (casing, centre, markers):
        line.appendSymbolLayer(sl)
    trails = add("trails", "multi-layer line", QgsSingleSymbolRenderer(line))

    # simple labeling on zones (categorized layer)
    pal = QgsPalLayerSettings()
    pal.fieldName = "name"
    fmt = QgsTextFormat()
    fmt.setSize(9)
    fmt.setColor(QColor("#222222"))
    pal.setFormat(fmt)
    labelled = project.mapLayersByName("categorized")[0]
    labelled.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    labelled.setLabelsEnabled(True)

    # rule-based labeling on trails
    lbl_root = QgsRuleBasedLabeling.Rule(None)
    major = QgsPalLayerSettings()
    major.fieldName = "name"
    major_rule = QgsRuleBasedLabeling.Rule(major)
    major_rule.setFilterExpression("\"class\" = 'major'")
    major_rule.setDescription("Major trails")
    lbl_root.appendChild(major_rule)
    trails.setLabeling(QgsRuleBasedLabeling(lbl_root))
    trails.setLabelsEnabled(True)

    # Only the first few layers visible so a render is readable.
    for node in root.findLayers()[5:]:
        node.setItemVisibilityChecked(False)

    _write(project, out / "styling.qgz")


def make_layout(out, gpkg, svg):
    project = new_project("Fixture: layout")
    zones, sites, trails = load(gpkg, "zones"), load(gpkg, "sites"), load(gpkg, "trails")
    zones.setRenderer(QgsSingleSymbolRenderer(_fill("#dfe7dd")))
    sites.setRenderer(QgsSingleSymbolRenderer(_marker("#b5462f")))
    for lyr in (zones, trails, sites):
        project.addMapLayer(lyr)
    extent = zones.extent().buffered(200)

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()  # one A4 landscape page
    layout.setName("Main")
    mm = Qgis.LayoutUnit.Millimeters

    def place(item, x, y, w=None, h=None, item_id=None):
        layout.addLayoutItem(item)
        item.attemptMove(QgsLayoutPoint(x, y, mm))
        if w is not None:
            item.attemptResize(QgsLayoutSize(w, h, mm))
        if item_id:
            item.setId(item_id)
        return item

    main_map = QgsLayoutItemMap(layout)
    main_map.setExtent(extent)
    main_map.setFrameEnabled(True)
    place(main_map, 10, 20, 180, 150, "main map")
    grid = QgsLayoutItemMapGrid("Grid 1", main_map)
    grid.setIntervalX(1000)
    grid.setIntervalY(1000)
    grid.setAnnotationEnabled(True)
    main_map.grids().addGrid(grid)

    inset = QgsLayoutItemMap(layout)
    inset.setExtent(extent.buffered(3000))
    inset.setFrameEnabled(True)
    place(inset, 200, 20, 80, 60, "inset map")
    ov = QgsLayoutItemMapOverview("Overview 1", inset)
    ov.setLinkedMap(main_map)
    inset.overviews().addOverview(ov)

    legend = QgsLayoutItemLegend(layout)
    legend.setTitle("Legend")
    legend.setLinkedMap(main_map)
    place(legend, 200, 85, None, None, "legend")

    bar = QgsLayoutItemScaleBar(layout)
    bar.setStyle("Single Box")
    bar.setLinkedMap(main_map)
    bar.applyDefaultSize()
    place(bar, 10, 175, None, None, "scale bar")

    title = QgsLayoutItemLabel(layout)
    title.setText("Fixture layout: [% @project_title %]")
    fmt = QgsTextFormat()
    fmt.setSize(16)
    title.setTextFormat(fmt)
    place(title, 10, 5, 180, 12, "title")

    pic = QgsLayoutItemPicture(layout)
    pic.setPicturePath(str(svg))
    place(pic, 270, 150, 15, 15, "north arrow")

    rect = QgsLayoutItemShape(layout)
    rect.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
    place(rect, 200, 140, 30, 20, "rectangle")
    ellipse = QgsLayoutItemShape(layout)
    ellipse.setShapeType(QgsLayoutItemShape.Shape.Ellipse)
    place(ellipse, 235, 140, 30, 20, "ellipse")

    poly = QgsLayoutItemPolygon(QPolygonF([QPointF(200, 165), QPointF(215, 180), QPointF(185, 180)]), layout)
    layout.addLayoutItem(poly)
    poly.setId("triangle")
    pline = QgsLayoutItemPolyline(QPolygonF([QPointF(220, 165), QPointF(240, 180), QPointF(260, 165)]), layout)
    layout.addLayoutItem(pline)
    pline.setId("zigzag")

    marker = QgsLayoutItemMarker(layout)
    place(marker, 265, 185, None, None, "marker")

    table = QgsLayoutItemAttributeTable.create(layout)
    table.setVectorLayer(zones)
    table.setMaximumNumberOfFeatures(5)
    layout.addMultiFrame(table)
    frame = QgsLayoutFrame(layout, table)
    frame.attemptMove(QgsLayoutPoint(10, 185, mm))
    frame.attemptResize(QgsLayoutSize(90, 20, mm))
    table.addFrame(frame)

    manual = QgsLayoutItemManualTable.create(layout)
    manual.setTableContents([[QgsTableCell("Key"), QgsTableCell("Value")], [QgsTableCell("CRS"), QgsTableCell(CRS)]])
    layout.addMultiFrame(manual)
    mframe = QgsLayoutFrame(layout, manual)
    mframe.attemptMove(QgsLayoutPoint(105, 185, mm))
    mframe.attemptResize(QgsLayoutSize(60, 20, mm))
    manual.addFrame(mframe)

    project.layoutManager().addLayout(layout)

    # Atlas layout over the zones.
    atlas_layout = QgsPrintLayout(project)
    atlas_layout.initializeDefaults()
    atlas_layout.setName("Atlas by zone")
    amap = QgsLayoutItemMap(atlas_layout)
    amap.setExtent(extent)
    atlas_layout.addLayoutItem(amap)
    amap.attemptMove(QgsLayoutPoint(10, 10, mm))
    amap.attemptResize(QgsLayoutSize(200, 180, mm))
    amap.setAtlasDriven(True)
    amap.setAtlasScalingMode(QgsLayoutItemMap.AtlasScalingMode.Auto)
    amap.setAtlasMargin(0.1)
    atlas = atlas_layout.atlas()
    atlas.setCoverageLayer(zones)
    atlas.setEnabled(True)
    atlas.setPageNameExpression("\"name\"")
    atlas.setFilenameExpression("'zone_' || \"id\"")
    project.layoutManager().addLayout(atlas_layout)

    # Report with a field-group section.
    report = QgsReport(project)
    report.setName("Zone report")
    section = QgsReportSectionFieldGroup()
    section.setLayer(zones)
    section.setField("zone")
    report.appendChild(section)
    project.layoutManager().addLayout(report)

    _write(project, out / "layout.qgz")

    # Sanity: the main layout must render a page (catches broken items early).
    exporter = QgsLayoutExporter(layout)
    if exporter.renderPageToImage(0, dpi=40).isNull():
        raise RuntimeError("layout page render returned an empty image")


def _write(project, path):
    if not project.write(str(path)):
        raise RuntimeError(f"cannot write {path}: {project.error()}")
    print(f"wrote {path}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "generated"), help="output folder")
    args = ap.parse_args(argv)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    app = QgsApplication([], False)
    app.initQgis()
    try:
        gpkg = out / "fixture_data.gpkg"
        write_data(gpkg)
        assets = out / "assets"
        assets.mkdir(exist_ok=True)
        svg = assets / "north.svg"
        shutil.copyfile(REPO_ICON, svg)
        make_basic(out, gpkg)
        make_styling(out, gpkg)
        make_layout(out, gpkg, svg)
    finally:
        _model.keep.clear()
        app.exitQgis()
    return 0


if __name__ == "__main__":
    sys.exit(main())

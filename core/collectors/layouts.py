# SPDX-License-Identifier: GPL-2.0-or-later
"""Layout collectors: print layouts, reports, pages, every item (position, size, properties),
multiframe tables, atlas, page and item images, and the layout template (.qpt).

Design section 5 "Layouts" and section 6 (visual outputs are the critical part).
"""

import os

from qgis.core import (
    QgsApplication,
    QgsLayoutExporter,
    QgsLayoutFrame,
    QgsLayoutItem,
    QgsLayoutItemAttributeTable,
    QgsLayoutItemGroup,
    QgsLayoutItemHtml,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemManualTable,
    QgsLayoutItemMap,
    QgsLayoutItemMarker,
    QgsLayoutItemPage,
    QgsLayoutItemPicture,
    QgsLayoutItemPolygon,
    QgsLayoutItemPolyline,
    QgsLayoutItemScaleBar,
    QgsLayoutItemShape,
    QgsLayoutObject,
    QgsLayerTreeGroup,
    QgsPrintLayout,
    QgsReadWriteContext,
    QgsReport,
    QgsReportSectionFieldGroup,
    QgsReportSectionLayout,
)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtXml import QDomDocument

from ..redact import redact_named_value
from ..safe_paths import sanitize_name
from ..xmlwalk import flatten, redact_dom
from ..paths import PathStyle
from .common import enum_name, finite, rect_list, safe_message
from .styling import _expand, color_hex, data_defined, symbol_doc

MAX_IMAGE_PIXELS = 16_000_000  # per rendered image (DoS bound)
CLOSE_UP_TYPES = (QgsLayoutItemMap, QgsLayoutItemLegend, QgsLayoutItemScaleBar)
MAX_ITEMS_PER_LAYOUT = 2000


# --------------------------------------------------------------------------- crash guard


def render_hazard(item):
    """Why painting this item would crash QGIS, or None.

    A segfault cannot be caught (qgis-plugin skill, golden rule 1), so known crashers are
    avoided instead. QGIS 4.2.3: QgsLayoutItemChart::prepareGatherer dereferences a missing
    source layer; a chart whose layer is absent or not loaded (e.g. a web layer that was not
    contacted) crashes the renderer.
    """
    try:
        from qgis.core import QgsLayoutItemChart
    except ImportError:  # older QGIS without chart items
        return None
    if isinstance(item, QgsLayoutItemChart) and item.isVisible():
        layer = item.sourceLayer()
        if layer is None or not layer.isValid():
            return "a chart item without a loaded source layer (QGIS would crash drawing it)"
    return None


def _hazards(layout):
    return [
        (it, reason)
        for it in layout.items()
        if isinstance(it, QgsLayoutItem)
        for reason in [render_hazard(it)]
        if reason
    ]


# --------------------------------------------------------------------------- helpers


def _dpi_for(width_mm, height_mm, dpi):
    """Requested dpi, lowered so the image stays within MAX_IMAGE_PIXELS."""
    w_in, h_in = max(width_mm, 1) / 25.4, max(height_mm, 1) / 25.4
    cap = (MAX_IMAGE_PIXELS / (w_in * h_in)) ** 0.5
    return max(24, int(min(dpi, cap)))


def _text_format(fmt):
    if fmt is None:
        return None
    font = fmt.font()
    return {
        "font_family": font.family(),
        "font_style": fmt.namedStyle() or None,
        "size": finite(fmt.size(), 3),
        "size_unit": enum_name(fmt.sizeUnit()),
        "color": color_hex(fmt.color()),
        "buffer": fmt.buffer().enabled(),
        "background": fmt.background().enabled(),
        "shadow": fmt.shadow().enabled(),
    }


def _item_xml_properties(item):
    """Every attribute QGIS writes for the item (complete record for the JSON)."""
    doc = QDomDocument()
    parent = doc.createElement("items")
    item.writeXml(parent, doc, QgsReadWriteContext())
    el = parent.firstChildElement()
    flat = {}
    for k, v in flatten(
        el,
        skip=(
            "symbol",
            "LayoutObject",
            "Extent",
            "layerSet",
            "ComposerMapGrid",
            "ComposerMapOverview",
            "layerTreeGroup",
            "dataDefinedProperties",
        ),
    ).items():
        _expand(flat, k, v)
    return flat


def _display(item):
    return item.displayName() if item is not None else None


def _path_doc(path, paths):
    if not path:
        return None
    if path.startswith(("http://", "https://", "base64:")):
        return {
            "path": path[:200] if path.startswith("base64:") else path,
            "embedded": path.startswith("base64:"),
            "exists": None,
            "relative": None,
        }
    full = paths.absolute(path)
    return {
        "path": paths.show(path),  # as the `paths` option asks
        "embedded": False,
        "exists": os.path.exists(full),
        "relative": PathStyle(paths.dir, "relative").show(path) if paths.dir else None,
    }


# --------------------------------------------------------------------------- item details


def _map_details(item):
    ext = item.extent()
    d = {
        "extent": rect_list(ext)
        or [finite(ext.xMinimum()), finite(ext.yMinimum()), finite(ext.xMaximum()), finite(ext.yMaximum())],
        "empty_extent": ext.isEmpty(),
        "scale": finite(item.scale()),
        "crs": item.crs().authid() if item.crs().isValid() else None,
        "map_rotation": finite(item.mapRotation()),
        "keep_layer_set": item.keepLayerSet(),
        "layers": [lyr.name() for lyr in item.layers()] if item.keepLayerSet() else None,
        "keep_styles": item.keepLayerStyles(),
        "follow_theme": item.followVisibilityPreset(),
        "theme": item.followVisibilityPresetName() or None,
        "atlas_driven": item.atlasDriven(),
        "atlas_scaling": enum_name(item.atlasScalingMode()) if item.atlasDriven() else None,
        "atlas_margin": finite(item.atlasMargin()) if item.atlasDriven() else None,
        "grids": [],
        "overviews": [],
    }
    for g in item.grids().asList():
        d["grids"].append({
            "name": g.name(),
            "enabled": g.enabled(),
            "style": enum_name(g.style()),
            "units": enum_name(g.units()),
            "interval": [finite(g.intervalX()), finite(g.intervalY())],
            "offset": [finite(g.offsetX()), finite(g.offsetY())],
            "crs": g.crs().authid() if g.crs().isValid() else None,
            "annotations": g.annotationEnabled(),
            "annotation_format": enum_name(g.annotationFormat()) if g.annotationEnabled() else None,
            "frame_style": enum_name(g.frameStyle()),
        })
    for ov in item.overviews().asList():
        d["overviews"].append({
            "name": ov.name(),
            "enabled": ov.enabled(),
            "linked_map": _display(ov.linkedMap()),
            "frame_symbol": symbol_doc(ov.frameSymbol().clone()) if ov.frameSymbol() else None,
        })
    return d


def _legend_entries(group, depth=0):
    out = []
    for child in group.children():
        title = child.customProperty("legend/title-label") or child.name()
        entry = {"name": title, "kind": "group" if isinstance(child, QgsLayerTreeGroup) else "layer", "children": []}
        if isinstance(child, QgsLayerTreeGroup) and depth < 10:
            entry["children"] = _legend_entries(child, depth + 1)
        out.append(entry)
    return out


def item_details(item, paths):
    """Type-specific settings for the common item types; {} for the rest (JSON has all XML)."""
    if isinstance(item, QgsLayoutItemMap):
        return _map_details(item)
    if isinstance(item, QgsLayoutItemLabel):
        return {
            "text": item.text(),
            "mode": enum_name(item.mode()),
            "font": _text_format(item.textFormat()),
            "h_align": enum_name(item.hAlign()),
            "v_align": enum_name(item.vAlign()),
            "margin": [finite(item.marginX()), finite(item.marginY())],
        }
    if isinstance(item, QgsLayoutItemLegend):
        model = item.model()
        return {
            "title": item.title(),
            "linked_map": _display(item.linkedMap()),
            # syncMode() replaces autoUpdateModel() in QGIS 4.
            "sync_mode": enum_name(item.syncMode()) if hasattr(item, "syncMode") else None,
            "auto_update": enum_name(item.syncMode()) != "Manual"
            if hasattr(item, "syncMode")
            else item.autoUpdateModel(),
            "columns": item.columnCount(),
            "filter_by_map": item.legendFilterByMapEnabled(),
            "auto_size": item.resizeToContents(),
            "entries": _legend_entries(model.rootGroup()) if model and model.rootGroup() else [],
        }
    if isinstance(item, QgsLayoutItemScaleBar):
        return {
            "style": item.style(),
            "units": enum_name(item.units()),
            "unit_label": item.unitLabel(),
            "segments_right": item.numberOfSegments(),
            "segments_left": item.numberOfSegmentsLeft(),
            "units_per_segment": finite(item.unitsPerSegment()),
            "map_units_per_unit": finite(item.mapUnitsPerScaleBarUnit()),
            "height": finite(item.height()),
            "linked_map": _display(item.linkedMap()),
            "font": _text_format(item.textFormat()),
        }
    if isinstance(item, QgsLayoutItemPicture):
        return {
            "source": _path_doc(item.picturePath(), paths),
            "format": enum_name(item.mode()),
            "resize_mode": enum_name(item.resizeMode()),
            "north_arrow_map": _display(item.linkedMap()),
            "svg_fill": color_hex(item.svgFillColor()),
            "svg_stroke": color_hex(item.svgStrokeColor()),
        }
    if isinstance(item, QgsLayoutItemShape):
        return {
            "shape": enum_name(item.shapeType()),
            "corner_radius": finite(item.cornerRadius().length()),
            "symbol": symbol_doc(item.symbol().clone()) if item.symbol() else None,
        }
    if isinstance(item, (QgsLayoutItemPolygon, QgsLayoutItemPolyline)):
        poly = item.nodes()
        nodes = [[finite(poly.at(i).x(), 3), finite(poly.at(i).y(), 3)] for i in range(poly.count())]
        sym = item.symbol()
        return {"nodes": nodes, "symbol": symbol_doc(sym.clone()) if sym else None}
    if isinstance(item, QgsLayoutItemMarker):
        return {
            "symbol": symbol_doc(item.symbol().clone()) if item.symbol() else None,
            "north_arrow_map": _display(item.linkedMap()),
        }
    if isinstance(item, QgsLayoutFrame):
        mf = item.multiFrame()
        return {"multiframe": mf.displayName() if mf else None, "hide_if_empty": item.hidePageIfEmpty()}
    if isinstance(item, QgsLayoutItemGroup):
        return {"members": [_display(i) for i in item.items()]}
    if hasattr(item, "sourceLayer") and hasattr(item, "seriesList"):  # chart (QGIS 4)
        layer = item.sourceLayer()
        plot = item.plot()
        return {
            "source_layer": layer.name() if layer else None,
            "plot_type": plot.type() if plot is not None and hasattr(plot, "type") else None,
            "series": [
                {"name": s.name(), "x": s.xExpression(), "y": s.yExpression(), "filter": s.filterExpression() or None}
                for s in item.seriesList()
            ],
        }
    return {}


def item_doc(item, registry, paths):
    meta = registry.itemMetadata(item.type())
    pos, size = item.pagePositionWithUnits(), item.sizeWithUnits()
    return {
        "uuid": item.uuid(),
        "id": item.id(),
        "name": item.displayName(),
        "type_id": int(item.type()),
        "type": meta.visibleName() if meta else type(item).__name__,
        "page": item.page() + 1,
        "position": [finite(pos.x(), 3), finite(pos.y(), 3)],
        "size": [finite(size.width(), 3), finite(size.height(), 3)],
        "units": enum_name(pos.units()),
        "reference_point": enum_name(item.referencePoint()),
        "rotation": finite(item.itemRotation(), 3),
        "z": finite(item.zValue()),
        "visible": item.isVisible(),
        "locked": item.isLocked(),
        "exclude_from_exports": item.excludeFromExports(),
        "frame": {
            "enabled": item.frameEnabled(),
            "color": color_hex(item.frameStrokeColor()),
            "width": finite(item.frameStrokeWidth().length()),
        },
        "background": {"enabled": item.hasBackground(), "color": color_hex(item.backgroundColor())},
        "opacity": finite(item.itemOpacity(), 4),
        "blend_mode": enum_name(item.blendMode()).replace("CompositionMode_", ""),
        "data_defined": data_defined(item.dataDefinedProperties(), QgsLayoutObject.propertyDefinitions()),
        "details": item_details(item, paths),
        "properties": _item_xml_properties(item),
        "image": None,
    }


def multiframe_doc(mf, registry):
    meta = registry.multiFrameMetadata(mf.type())
    doc = {
        "uuid": mf.uuid(),
        "name": mf.displayName(),
        "type": meta.visibleName() if meta else type(mf).__name__,
        "frames": [f.displayName() for f in mf.frames()],
        "resize_mode": enum_name(mf.resizeMode()),
        "data_defined": data_defined(mf.dataDefinedProperties(), QgsLayoutObject.propertyDefinitions()),
    }
    if isinstance(mf, QgsLayoutItemAttributeTable):
        layer = mf.vectorLayer()
        doc.update({
            "source": enum_name(mf.source()),
            "layer": layer.name() if layer else None,
            "layer_id": layer.id() if layer else None,
            "max_features": mf.maximumNumberOfFeatures(),
            "filter": mf.featureFilter() if mf.filterFeatures() else None,
            "filter_to_atlas": mf.filterToAtlasFeature(),
            "only_visible_features": mf.displayOnlyVisibleFeatures(),
            "columns": [{"heading": c.heading(), "attribute": c.attribute()} for c in mf.columns()],
        })
    elif isinstance(mf, QgsLayoutItemManualTable):
        doc["rows"] = [
            [cell.content() if isinstance(cell.content(), str) else str(cell.content()) for cell in row]
            for row in mf.tableContents()[:200]
        ]
        doc["header_row"] = mf.includeTableHeader()
    elif isinstance(mf, QgsLayoutItemHtml):
        doc.update({
            "content_mode": enum_name(mf.contentMode()),
            "url": mf.url().toString() or None,
            "html_length": len(mf.html() or ""),
        })
    return doc


# --------------------------------------------------------------------------- layouts


def _atlas_doc(layout):
    atlas = layout.atlas()
    layer = atlas.coverageLayer()
    return {
        "enabled": atlas.enabled(),
        "coverage_layer": layer.name() if layer else None,
        "coverage_layer_id": layer.id() if layer else None,
        "hide_coverage": atlas.hideCoverage(),
        "page_name": atlas.pageNameExpression() or None,
        "filter": atlas.filterExpression() if atlas.filterFeatures() else None,
        "sort": atlas.sortExpression() if atlas.sortFeatures() else None,
        "sort_ascending": atlas.sortAscending() if atlas.sortFeatures() else None,
        "filename": atlas.filenameExpression() or None,
        "feature_count": None,
    }


def _variables(layout, model, redact):
    names = layout.customProperty("variableNames") or []
    values = layout.customProperty("variableValues") or []
    out = []
    for name, value in zip(
        names if isinstance(names, list) else [names], values if isinstance(values, list) else [values]
    ):
        value = str(value)
        if redact:
            value, kinds = redact_named_value(name, value)
            model.count_redactions(kinds)
        out.append({"name": name, "value": value})
    return out


def _render_images(layout, doc, items_by_uuid, sink, stem, dpi, model):
    exporter = QgsLayoutExporter(layout)
    pages = layout.pageCollection()
    hazards = _hazards(layout)
    hazard_pages = {it.page() for it, _r in hazards}
    for it, reason in hazards:
        model.add_problem(
            "warning",
            "layouts",
            f"Layout '{layout.name()}', item '{it.displayName()}': {reason}. Page {it.page() + 1} and overlapping "
            "close-ups were not rendered.",
        )
    for i in range(pages.pageCount()):
        if i in hazard_pages:
            continue
        size = pages.page(i).pageSize()
        page_dpi = _dpi_for(size.width(), size.height(), dpi)
        img = exporter.renderPageToImage(i, QSize(), page_dpi)
        doc["pages"][i]["image"] = sink.add_png(f"layouts/{stem}/page_{i + 1:02d}.png", img)
    for item in layout.items():
        if isinstance(item, CLOSE_UP_TYPES) and item.uuid() in items_by_uuid and item.isVisible():
            rect = item.sceneBoundingRect()
            if rect.width() < 1 or rect.height() < 1:
                continue
            if any(rect.intersects(h.sceneBoundingRect()) for h, _r in hazards):
                continue
            item_dpi = _dpi_for(rect.width(), rect.height(), dpi * 2)
            img = exporter.renderRegionToImage(rect, QSize(), item_dpi)
            name = f"layouts/{stem}/item_{sanitize_name(item.displayName(), 'item', 40)}_{item.uuid()[1:9]}.png"
            items_by_uuid[item.uuid()]["image"] = sink.add_png(name, img)
    atlas = layout.atlas()
    if doc["atlas"] and doc["atlas"]["enabled"] and atlas.coverageLayer() and atlas.coverageLayer().isValid():
        try:
            if atlas.beginRender():
                doc["atlas"]["feature_count"] = atlas.count()
                if atlas.first() and 0 not in hazard_pages:
                    size = pages.page(0).pageSize()
                    img = QgsLayoutExporter(layout).renderPageToImage(
                        0, QSize(), _dpi_for(size.width(), size.height(), dpi)
                    )
                    doc["atlas"]["first_page_image"] = sink.add_png(f"layouts/{stem}/atlas_first_page.png", img)
        finally:
            atlas.endRender()


def print_layout_doc(layout, model, options, sink, stem, paths):
    registry = QgsApplication.layoutItemRegistry()
    pages = layout.pageCollection()
    doc = {
        "name": layout.name(),
        "kind": "print_layout",
        "pages": [],
        "items": [],
        "multiframes": [],
        "atlas": _atlas_doc(layout) if isinstance(layout, QgsPrintLayout) else None,
        "variables": _variables(layout, model, options.redact),
        "template": None,
    }
    for i in range(pages.pageCount()):
        page = pages.page(i)
        size = page.pageSize()
        doc["pages"].append({
            "number": i + 1,
            "size": [finite(size.width(), 3), finite(size.height(), 3)],
            "units": enum_name(size.units()),
            "orientation": "landscape" if size.width() > size.height() else "portrait",
            "image": None,
        })
    items = [it for it in layout.items() if isinstance(it, QgsLayoutItem) and not isinstance(it, QgsLayoutItemPage)]
    items.sort(key=lambda it: (it.page(), -it.zValue()))  # top of the Items panel first
    if len(items) > MAX_ITEMS_PER_LAYOUT:
        model.add_problem(
            "info",
            "layouts",
            f"Layout '{layout.name()}' has {len(items)} items; the first {MAX_ITEMS_PER_LAYOUT} are documented.",
        )
        items = items[:MAX_ITEMS_PER_LAYOUT]
    by_uuid = {}
    for item in items:
        try:
            d = item_doc(item, registry, paths)
        except Exception as exc:  # principle 7
            d = {
                "uuid": item.uuid(),
                "name": item.displayName(),
                "type": type(item).__name__,
                "error": safe_message(exc),
            }
            model.add_problem(
                "error", "layouts", f"Item '{item.displayName()}' in '{layout.name()}': {safe_message(exc)}"
            )
        doc["items"].append(d)
        by_uuid[item.uuid()] = d
    for mf in layout.multiFrames():
        try:
            doc["multiframes"].append(multiframe_doc(mf, registry))
        except Exception as exc:
            model.add_problem(
                "error", "layouts", f"Table or frame '{mf.displayName()}' in '{layout.name()}': {safe_message(exc)}"
            )
    for d in doc["items"]:
        if (d.get("details") or {}).get("empty_extent"):
            model.add_problem(
                "warning", "layouts", f"Map '{d['name']}' in '{layout.name()}' has an empty extent and draws nothing."
            )
        pic = (d.get("details") or {}).get("source")
        if isinstance(pic, dict) and pic.get("exists") is False:
            model.add_problem(
                "warning", "layouts", f"Picture '{d['name']}' in '{layout.name()}' points to a missing file."
            )
    if options.images:
        try:
            _render_images(layout, doc, by_uuid, sink, stem, options.image_dpi, model)
        except Exception as exc:
            model.add_problem(
                "error", "layouts", f"Layout '{layout.name()}' could not be rendered: {safe_message(exc)}"
            )
    return doc


def _report_sections(section, depth=0):
    out = []
    for i in range(section.childCount()):
        child = section.childSection(i)
        entry = {"type": type(child).__name__.replace("QgsReportSection", ""), "children": []}
        if isinstance(child, QgsReportSectionFieldGroup):
            layer = child.layer()
            entry.update({
                "layer": layer.name() if layer else None,
                "field": child.field(),
                "ascending": child.sortAscending(),
                "body": child.bodyEnabled(),
                "header": child.headerEnabled(),
                "footer": child.footerEnabled(),
            })
        elif isinstance(child, QgsReportSectionLayout):
            entry.update({
                "body": child.bodyEnabled(),
                "header": child.headerEnabled(),
                "footer": child.footerEnabled(),
            })
        if depth < 10:
            entry["children"] = _report_sections(child, depth + 1)
        out.append(entry)
    return out


def report_doc(report):
    return {
        "name": report.name(),
        "kind": "report",
        "header": report.headerEnabled(),
        "footer": report.footerEnabled(),
        "sections": _report_sections(report),
        "template": None,
    }


def _save_template(layout, sink, stem, redact, ext):
    doc = QDomDocument()
    doc.appendChild(layout.writeLayoutXml(doc, QgsReadWriteContext()))
    if redact:
        redact_dom(doc)
    return sink.add_text(f"layouts/{stem}.{ext}", doc.toString(2))


def collect_layouts(project, model, options, sink, feedback=None):
    project_dir = os.path.dirname(project.fileName()) if project.fileName() else None
    paths = PathStyle(project_dir, options.paths)
    for n, layout in enumerate(project.layoutManager().layouts(), 1):
        if feedback is not None and feedback.isCanceled():
            return False
        stem = f"{n:02d}_{sanitize_name(layout.name(), 'layout', 40)}"
        try:
            if isinstance(layout, QgsReport):
                doc = report_doc(layout)
                doc["template"] = _save_template(layout, sink, stem, options.redact, "xml")
            else:
                doc = print_layout_doc(layout, model, options, sink, stem, paths)
                doc["template"] = _save_template(layout, sink, stem, options.redact, "qpt")
        except Exception as exc:  # principle 7
            model.add_problem("error", "layouts", f"Layout '{layout.name()}' could not be read: {safe_message(exc)}")
            continue
        model.layouts.append(doc)
    return True

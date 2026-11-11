# SPDX-License-Identifier: GPL-2.0-or-later
"""Styling collectors: renderers, symbols and symbol layers, labeling, raster renderers, QML,
legend and symbol images (docs/DESIGN.md section 5 "Styling", section 6).

Every symbol layer is recorded with ALL its properties plus the list of properties that differ
from the default of its type, so the human report can show "only what you changed" while the
JSON stays complete.

Crash rule (qgis-plugin skill): a symbol owned by a category, range or rule is cloned while its
container is still alive; no symbol object is ever shared between two owners.
"""

from qgis.core import (
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsHeatmapRenderer,
    QgsInvertedPolygonRenderer,
    QgsMapLayer,
    QgsPaintEffectRegistry,
    QgsPalLayerSettings,
    QgsPointClusterRenderer,
    QgsPointDisplacementRenderer,
    QgsRasterLayer,
    QgsReadWriteContext,
    QgsRenderContext,
    QgsRuleBasedLabeling,
    QgsRuleBasedRenderer,
    QgsSingleBandPseudoColorRenderer,
    QgsPalettedRasterRenderer,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsSymbolLayer,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QImage, QPainter
from qgis.PyQt.QtXml import QDomDocument

from ..xmlwalk import active_data_defined, attributes, flatten, option_value, redact_dom
from .common import enum_name, finite, safe_message

MAX_LEGEND_ITEMS = 200  # per layer; more are summarised, not rendered (DoS bound)
MAX_RULE_DEPTH = 12
# Every style category except custom properties (plugins store arbitrary data there, including
# secrets; they are documented separately with redaction). Combined with |, since ~ on a PyQt6
# enum yields a plain int that exportNamedStyle rejects.
_QML_EXCLUDED = {"CustomProperties", "AllVisualStyleCategories", "AllAttributeCategories", "AllStyleCategories"}
QML_CATEGORIES = None
for _cat in QgsMapLayer.StyleCategory:
    if _cat.name not in _QML_EXCLUDED:
        QML_CATEGORIES = _cat if QML_CATEGORIES is None else QML_CATEGORIES | _cat

# QGIS 4 does not expose the raster renderer registry to Python; names as shown in Symbology.
RASTER_RENDERER_NAMES = {
    "singlebandpseudocolor": "Singleband pseudocolor",
    "singlebandgray": "Singleband gray",
    "multibandcolor": "Multiband color",
    "paletted": "Paletted/Unique values",
    "hillshade": "Hillshade",
    "singlecolor": "Single color",
    "contour": "Contours",
}

_default_props_cache = {}
_default_label_cache = {}


# --------------------------------------------------------------------------- small helpers


def color_hex(color):
    if color is None or not color.isValid():
        return None
    return color.name(QColor.NameFormat.HexArgb) if color.alpha() < 255 else color.name()


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def _default_symbol_layer_props(layer_class):
    if layer_class not in _default_props_cache:
        props = {}
        meta = QgsApplication.symbolLayerRegistry().symbolLayerMetadata(layer_class)
        if meta is not None:
            sl = meta.createSymbolLayer({})
            if sl is not None:
                props = {k: _jsonable(v) for k, v in sl.properties().items()}
        _default_props_cache[layer_class] = props
    return _default_props_cache[layer_class]


def _symbol_layer_name(layer_class):
    meta = QgsApplication.symbolLayerRegistry().symbolLayerMetadata(layer_class)
    return meta.visibleName() if meta is not None else layer_class


def data_defined(collection, definitions):
    """Active data-defined overrides of a QgsPropertyCollection, with QGIS property names."""
    out = []
    if collection is None:
        return out
    for key in sorted(collection.propertyKeys()):
        prop = collection.property(key)
        if not prop or not prop.isActive():
            continue
        definition = definitions.get(key)
        kind = enum_name(prop.propertyType())
        out.append({
            "key": int(key),
            "name": definition.name() if definition else str(key),
            "description": definition.description() if definition else "",
            "type": kind,
            "expression": prop.expressionString() or None,
            "field": prop.field() or None,
            "value": _jsonable(prop.staticValue()) if kind == "StaticProperty" else None,
        })
    return out


def effect_doc(effect):
    """A paint effect, or None when absent or the untouched default stack."""
    if effect is None or QgsPaintEffectRegistry.isDefaultStack(effect):
        return None
    doc = {
        "type": effect.type(),
        "enabled": effect.enabled(),
        "properties": {k: _jsonable(v) for k, v in effect.properties().items()},
    }
    if hasattr(effect, "effectList"):
        doc["effects"] = [d for d in (effect_doc_any(e) for e in effect.effectList()) if d]
    return doc


def effect_doc_any(effect):
    """Like effect_doc but keeps every effect inside a stack (enabled or not)."""
    return {
        "type": effect.type(),
        "enabled": effect.enabled(),
        "properties": {k: _jsonable(v) for k, v in effect.properties().items()},
    }


def color_ramp_doc(ramp):
    if ramp is None:
        return None
    return {"type": ramp.type(), "properties": {k: _jsonable(v) for k, v in ramp.properties().items()}}


# --------------------------------------------------------------------------- symbols


def symbol_layer_doc(sl, depth=0):
    cls = sl.layerType()
    props = {k: _jsonable(v) for k, v in sl.properties().items()}
    defaults = _default_symbol_layer_props(cls)
    doc = {
        "class": cls,
        "name": _symbol_layer_name(cls),
        "enabled": sl.enabled(),
        "locked": sl.isLocked(),
        "properties": props,
        "non_default": sorted(k for k, v in props.items() if defaults.get(k) != v),
        "data_defined": data_defined(sl.dataDefinedProperties(), QgsSymbolLayer.propertyDefinitions()),
        "effect": effect_doc(sl.paintEffect()),
        "sub_symbol": None,
    }
    sub = sl.subSymbol()
    if sub is not None and depth < 4:
        doc["sub_symbol"] = symbol_doc(sub, depth + 1)
    return doc


def symbol_doc(symbol, depth=0):
    if symbol is None:
        return None
    doc = {
        "type": enum_name(symbol.type()),
        "opacity": finite(symbol.opacity(), 4),
        "color": color_hex(symbol.color()),
        "output_unit": enum_name(symbol.outputUnit()),
        "data_defined": data_defined(symbol.dataDefinedProperties(), QgsSymbol.propertyDefinitions()),
        "layers": [symbol_layer_doc(symbol.symbolLayer(i), depth) for i in range(symbol.symbolLayerCount())],
    }
    return doc


# --------------------------------------------------------------------------- vector renderers


def _renderer_attrs(renderer):
    doc = QDomDocument()
    el = renderer.save(doc, QgsReadWriteContext())
    attrs = attributes(el)
    attrs.pop("type", None)
    return attrs


def renderer_doc(renderer, legend_images, depth=0):
    """Describe a feature renderer. legend_images maps legend rule keys to image names."""
    if renderer is None:
        return None
    rtype = renderer.type()
    meta = QgsApplication.rendererRegistry().rendererMetadata(rtype)
    doc = {
        "type": rtype,
        "name": meta.visibleName() if meta is not None else rtype,
        "properties": _renderer_attrs(renderer),
        "order_by": renderer.orderBy().dump() if renderer.orderByEnabled() else None,
        "effect": effect_doc(renderer.paintEffect()),
    }
    if isinstance(renderer, QgsSingleSymbolRenderer):
        sym = renderer.symbol().clone() if renderer.symbol() else None
        doc["symbol"] = symbol_doc(sym)
        doc["image"] = next(iter(legend_images.values()), None)
    elif isinstance(renderer, QgsCategorizedSymbolRenderer):
        doc["attribute"] = renderer.classAttribute()
        doc["color_ramp"] = color_ramp_doc(renderer.sourceColorRamp())
        cats = renderer.categories()  # keep the list alive while cloning (use-after-free otherwise)
        doc["categories"] = [
            {
                "value": _jsonable(c.value()),
                "label": c.label(),
                "render": c.renderState(),
                "symbol": symbol_doc(c.symbol().clone() if c.symbol() else None),
                "image": legend_images.get(c.uuid()),
            }
            for c in cats
        ]
    elif isinstance(renderer, QgsGraduatedSymbolRenderer):
        doc["attribute"] = renderer.classAttribute()
        method = renderer.classificationMethod()
        doc["classification"] = {"id": method.id(), "name": method.name()} if method else None
        doc["graduated_method"] = enum_name(renderer.graduatedMethod())
        doc["color_ramp"] = color_ramp_doc(renderer.sourceColorRamp())
        ranges = renderer.ranges()
        doc["ranges"] = [
            {
                "lower": finite(r.lowerValue()),
                "upper": finite(r.upperValue()),
                "label": r.label(),
                "render": r.renderState(),
                "symbol": symbol_doc(r.symbol().clone() if r.symbol() else None),
                "image": legend_images.get(r.uuid()),
            }
            for r in ranges
        ]
    elif isinstance(renderer, QgsRuleBasedRenderer):
        doc["rules"] = [_rule_doc(rule, legend_images, 0) for rule in renderer.rootRule().children()]
    elif isinstance(renderer, (QgsPointClusterRenderer, QgsPointDisplacementRenderer, QgsInvertedPolygonRenderer)):
        if depth < 3:
            doc["embedded"] = renderer_doc(renderer.embeddedRenderer(), {}, depth + 1)
        if isinstance(renderer, QgsPointClusterRenderer):
            doc["cluster_symbol"] = symbol_doc(renderer.clusterSymbol().clone())
        if isinstance(renderer, QgsPointDisplacementRenderer) and renderer.centerSymbol():
            doc["center_symbol"] = symbol_doc(renderer.centerSymbol().clone())
    elif isinstance(renderer, QgsHeatmapRenderer):
        doc["color_ramp"] = color_ramp_doc(renderer.colorRamp())
        doc["weight_expression"] = renderer.weightExpression() or None
    else:
        # 2.5D and any renderer without a dedicated branch: document the symbols it draws.
        doc["symbols"] = [symbol_doc(s.clone()) for s in renderer.symbols(QgsRenderContext())]
    return doc


def _rule_doc(rule, legend_images, depth):
    doc = {
        "key": rule.ruleKey(),
        "label": rule.label(),
        "description": rule.description() or None,
        "filter": rule.filterExpression() or None,
        "else": rule.isElse(),
        "active": rule.active(),
        "min_scale": finite(rule.minimumScale()) or None,
        "max_scale": finite(rule.maximumScale()) or None,
        "symbol": symbol_doc(rule.symbol().clone()) if rule.symbol() else None,
        "image": legend_images.get(rule.ruleKey()),
        "children": [],
    }
    if depth < MAX_RULE_DEPTH:
        doc["children"] = [_rule_doc(child, legend_images, depth + 1) for child in rule.children()]
    return doc


# --------------------------------------------------------------------------- labeling


def _expand(out, key, value):
    if isinstance(value, dict):
        for k, v in value.items():
            _expand(out, f"{key}.{k}", v)
    elif isinstance(value, list):
        out[key] = ", ".join(str(v) for v in value if v is not None)
    else:
        out[key] = value


def pal_settings_flat(settings):
    """All label settings as {"section.attr": value}; data-defined and symbols separated."""
    doc = QDomDocument()
    el = settings.writeXml(doc, QgsReadWriteContext())
    raw = flatten(el, skip=("symbol", "dd_properties"))
    flat = {}
    for k, v in raw.items():
        _expand(flat, k, v)
    dd = []
    nodes = el.elementsByTagName("dd_properties")
    if nodes.count():
        opt = nodes.at(0).toElement().firstChildElement("Option")
        dd = active_data_defined(option_value(opt))
    return flat, dd


def _default_labels():
    if "pal" not in _default_label_cache:
        _default_label_cache["pal"] = pal_settings_flat(QgsPalLayerSettings())[0]
    return _default_label_cache["pal"]


def label_settings_doc(settings):
    flat, dd = pal_settings_flat(settings)
    defaults = _default_labels()
    return {
        "field": settings.fieldName,
        "is_expression": settings.isExpression,
        "settings": flat,
        "non_default": sorted(k for k, v in flat.items() if defaults.get(k) != v),
        "data_defined": dd,
    }


def labeling_doc(layer):
    if not isinstance(layer, QgsVectorLayer) or layer.labeling() is None:
        return None
    labeling = layer.labeling()
    doc = {"enabled": layer.labelsEnabled(), "type": labeling.type()}
    if isinstance(labeling, QgsVectorLayerSimpleLabeling):
        doc["settings"] = label_settings_doc(labeling.settings())
    elif isinstance(labeling, QgsRuleBasedLabeling):
        doc["rules"] = [_label_rule_doc(r, 0) for r in labeling.rootRule().children()]
    return doc


def _label_rule_doc(rule, depth):
    settings = rule.settings()
    doc = {
        "key": rule.ruleKey(),
        "description": rule.description() or None,
        "filter": rule.filterExpression() or None,
        "else": rule.isElse(),
        "active": rule.active(),
        "min_scale": finite(rule.minimumScale()) or None,
        "max_scale": finite(rule.maximumScale()) or None,
        "settings": label_settings_doc(settings) if settings else None,
        "children": [],
    }
    if depth < MAX_RULE_DEPTH:
        doc["children"] = [_label_rule_doc(c, depth + 1) for c in rule.children()]
    return doc


# --------------------------------------------------------------------------- raster


def raster_renderer_doc(layer):
    renderer = layer.renderer()
    if renderer is None:
        return None
    rtype = renderer.type()
    doc = QDomDocument()
    parent = doc.createElement("pipe")
    renderer.writeXml(doc, parent)
    el = parent.firstChildElement()
    flat = {}
    for k, v in flatten(el, skip=("rastershader", "colorPalette")).items():
        _expand(flat, k, v)
    flat.pop("type", None)
    out = {
        "type": rtype,
        "name": RASTER_RENDERER_NAMES.get(rtype, rtype),
        "properties": flat,
        "opacity": finite(renderer.opacity(), 4),
    }
    if isinstance(renderer, QgsSingleBandPseudoColorRenderer):
        fn = renderer.shader().rasterShaderFunction() if renderer.shader() else None
        if fn is not None:
            out["band"] = renderer.inputBand()
            out["min"] = finite(renderer.classificationMin())
            out["max"] = finite(renderer.classificationMax())
            out["interpolation"] = enum_name(fn.colorRampType())
            out["classification_mode"] = enum_name(fn.classificationMode())
            out["color_ramp"] = color_ramp_doc(fn.sourceColorRamp())
            out["items"] = [
                {"value": finite(i.value), "color": color_hex(i.color), "label": i.label}
                for i in fn.colorRampItemList()
            ]
    elif isinstance(renderer, QgsPalettedRasterRenderer):
        out["band"] = renderer.inputBand()
        out["items"] = [
            {"value": finite(c.value), "color": color_hex(c.color), "label": c.label} for c in renderer.classes()
        ]
    out["pipe"] = _raster_pipe(layer)
    return out


def _raster_pipe(layer):
    pipe = {}
    bc = layer.brightnessFilter()
    if bc is not None:
        pipe["brightness"] = bc.brightness()
        pipe["contrast"] = bc.contrast()
        pipe["gamma"] = finite(bc.gamma(), 4)
    hs = layer.hueSaturationFilter()
    if hs is not None:
        pipe["saturation"] = hs.saturation()
        pipe["grayscale_mode"] = enum_name(hs.grayscaleMode())
        pipe["colorize"] = hs.colorizeOn()
        pipe["invert_colors"] = hs.invertColors() if hasattr(hs, "invertColors") else None
    rs = layer.resampleFilter()
    if rs is not None:
        zin, zout = rs.zoomedInResampler(), rs.zoomedOutResampler()
        pipe["zoomed_in_resampling"] = zin.type() if zin else "nearest"
        pipe["zoomed_out_resampling"] = zout.type() if zout else "nearest"
        pipe["max_oversampling"] = finite(rs.maxOversampling())
    return pipe


# --------------------------------------------------------------------------- images


def _swatch(color, size):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(color)
    return img


def _ramp_bar(ramp, width, height):
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)
    try:
        for x in range(width):
            painter.setPen(ramp.color(x / max(1, width - 1)))
            painter.drawLine(x, 0, x, height - 1)
    finally:
        painter.end()
    return img


def legend_doc(layer, sink, stem, swatch_px, model):
    """Legend entries with rendered images. Returns (entries, {rule_key: image_name})."""
    entries, by_key = [], {}
    if isinstance(layer, QgsVectorLayer) and layer.renderer() is not None:
        renderer = layer.renderer()
        items = renderer.legendSymbolItems()
        if len(items) > MAX_LEGEND_ITEMS:
            model.add_problem(
                "info",
                "styling",
                f"'{layer.name()}' has {len(items)} legend entries; images were made for the first {MAX_LEGEND_ITEMS}.",
                layer.id(),
            )
        for n, item in enumerate(items):
            symbol = item.symbol()
            image = None
            if symbol is not None and n < MAX_LEGEND_ITEMS:
                image = sink.add_png(
                    f"images/{stem}/legend_{n + 1:03d}.png", symbol.asImage(QSize(swatch_px, swatch_px))
                )
            entries.append({"label": item.label(), "key": item.ruleKey(), "level": item.level(), "image": image})
            if image:
                by_key[item.ruleKey()] = image
        if not items and not isinstance(renderer, QgsHeatmapRenderer):
            # Renderers without legend entries (2.5D, ...): render the symbols they draw.
            for n, symbol in enumerate(renderer.symbols(QgsRenderContext())[:MAX_LEGEND_ITEMS]):
                image = sink.add_png(
                    f"images/{stem}/symbol_{n + 1:03d}.png", symbol.asImage(QSize(swatch_px, swatch_px))
                )
                entries.append({"label": f"Symbol {n + 1}", "key": f"symbol{n}", "level": 0, "image": image})
        if isinstance(renderer, QgsHeatmapRenderer) and renderer.colorRamp() is not None:
            image = sink.add_png(
                f"images/{stem}/ramp.png", _ramp_bar(renderer.colorRamp(), swatch_px * 5, max(8, swatch_px // 2))
            )
            entries.append({"label": "Heatmap colour ramp (low to high)", "key": "ramp", "level": 0, "image": image})
    elif isinstance(layer, QgsRasterLayer) and layer.renderer() is not None:
        # The renderer's own list (the layer-level one is deprecated since QGIS 3.40).
        for n, (label, color) in enumerate(layer.renderer().legendSymbologyItems()[:MAX_LEGEND_ITEMS]):
            image = sink.add_png(f"images/{stem}/legend_{n + 1:03d}.png", _swatch(color, swatch_px))
            entries.append({"label": label, "key": str(n), "level": 0, "image": image, "color": color_hex(color)})
    return entries, by_key


# --------------------------------------------------------------------------- entry point


def collect_style(layer, model, options, sink, stem):
    """Style of one layer: renderer, labeling, legend images, named styles, QML file."""
    style = {"renderer": None, "labeling": None, "legend": [], "qml": None, "named_styles": None}
    swatch_px = max(16, round(32 * options.image_dpi / 96))
    try:
        legend, by_key = legend_doc(layer, sink, stem, swatch_px, model)
        style["legend"] = legend
        if isinstance(layer, QgsVectorLayer):
            style["renderer"] = renderer_doc(layer.renderer(), by_key)
            style["labeling"] = labeling_doc(layer)
        elif isinstance(layer, QgsRasterLayer):
            style["renderer"] = raster_renderer_doc(layer)
        manager = layer.styleManager()
        style["named_styles"] = {"current": manager.currentStyle(), "all": list(manager.styles())}
    except Exception as exc:  # principle 7
        model.add_problem(
            "error", "styling", f"'{layer.name()}' style could not be fully read: {safe_message(exc)}", layer.id()
        )

    try:
        doc = QDomDocument()
        err = layer.exportNamedStyle(doc, QgsReadWriteContext(), QML_CATEGORIES)
        if err:
            raise RuntimeError(err)
        if options.redact:
            # Same secrets as the layer source (already counted once), so not added to totals.
            redact_dom(doc)
        style["qml"] = sink.add_text(f"styles/{stem}.qml", doc.toString(2))
    except Exception as exc:
        model.add_problem(
            "warning", "styling", f"'{layer.name()}' QML could not be exported: {safe_message(exc)}", layer.id()
        )
    return style

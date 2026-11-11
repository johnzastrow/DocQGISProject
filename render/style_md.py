# SPDX-License-Identifier: GPL-2.0-or-later
"""Markdown chapters for layer styling: symbology, symbol layers, labels, raster rendering.

Reads the plain `style` dict that core/collectors/styling.py puts on each LayerDoc. Shows only
settings that differ from QGIS defaults; the JSON keeps every setting.
"""

import re

from .text import fmt_number, md_code, md_text

MAX_VALUE_CHARS = 160

# Display names for common symbol-layer property keys (QGIS 4 English UI wording).
PROP_LABELS = {
    "color": "Fill colour",
    "outline_color": "Stroke colour",
    "outline_width": "Stroke width",
    "outline_style": "Stroke style",
    "style": "Fill style",
    "joinstyle": "Join style",
    "capstyle": "Cap style",
    "line_color": "Colour",
    "line_width": "Stroke width",
    "line_style": "Stroke style",
    "customdash": "Dash pattern",
    "use_custom_dash": "Custom dash pattern",
    "name": "Shape or file",
    "size": "Size",
    "angle": "Rotation",
    "offset": "Offset",
    "interval": "Interval",
    "placements": "Placement",
    "placement": "Placement",
    "offset_along_line": "Offset along line",
    "rotate": "Rotate marker",
    "gradient_type": "Gradient type",
    "color1": "Colour 1",
    "color2": "Colour 2",
    "distance": "Spacing",
    "lineangle": "Rotation",
    "distance_x": "Horizontal distance",
    "distance_y": "Vertical distance",
    "font": "Font family",
    "chr": "Character",
    "horizontal_anchor_point": "Horizontal anchor",
    "vertical_anchor_point": "Vertical anchor",
    "scale_method": "Scale method",
    "geometryModifier": "Geometry generator expression",
    "SymbolType": "Generated geometry type",
}
UNIT_WORDS = {
    "MM": "mm",
    "Pixel": "px",
    "MapUnit": "map units",
    "Point": "pt",
    "Inch": "in",
    "Percentage": "%",
    "RenderMetersInMapUnits": "metres at scale",
}
# Label XML sections -> Layer Properties > Labels tab names.
LABEL_TABS = {
    "text-style": "Text",
    "families": "Text",
    "substitutions": "Text",
    "text-format": "Formatting",
    "text-buffer": "Buffer",
    "text-mask": "Mask",
    "background": "Background",
    "shadow": "Shadow",
    "placement": "Placement",
    "rendering": "Rendering",
    "callout": "Callouts",
}
_BOOL_KEY_RE = re.compile(r"(?i)(draw|enabled|^is[A-Z_]|^use|bold$|italic$|underline$|strikeout$|^show|^force)")
_COLOR_RE = re.compile(r"^(\d{1,3}),(\d{1,3}),(\d{1,3}),(\d{1,3})(,.*)?$")


# --------------------------------------------------------------------------- value formatting


def humanize(key):
    """'outline_width' / 'fontSizeUnit' -> 'Outline width' / 'Font size unit'."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(key)).replace("_", " ").replace("-", " ").strip()
    return s[:1].upper() + s[1:].lower() if s else s


def fmt_color(value):
    """'224,192,104,255,rgb:...' -> '#e0c068' (with alpha when not opaque); None if not a colour."""
    m = _COLOR_RE.match(str(value))
    if not m:
        return None
    r, g, b, a = (int(m.group(i)) for i in range(1, 5))
    if max(r, g, b, a) > 255:
        return None
    hexv = f"#{r:02x}{g:02x}{b:02x}"
    return f"{md_code(hexv)}" + (f" at {round(a / 2.55)} % opacity" if a < 255 else "")


def fmt_value(value):
    if value is None or value == "":
        return "Not set"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return fmt_number(value)
    if isinstance(value, dict):  # nested settings map: readable pairs, never a Python repr
        pairs = [f"{humanize(k)}: {fmt_value(v)}" for k, v in value.items() if not isinstance(v, (dict, list))]
        text = "; ".join(pairs[:8]) + ("; ..." if len(pairs) > 8 else "")
        return text or "Nested settings (see project.json)"
    if isinstance(value, list):
        return md_text(", ".join(str(v) for v in value[:10])) + (", ..." if len(value) > 10 else "")
    s = str(value)
    if s.lstrip().startswith("<"):  # an embedded XML fragment (e.g. a callout's symbol)
        return "Embedded symbol definition (see the QML file)"
    color = fmt_color(s)
    if color:
        return color
    if len(s) > MAX_VALUE_CHARS:
        s = s[:MAX_VALUE_CHARS] + "..."
    if re.fullmatch(r"[A-Za-z][A-Za-z ]{0,30}", s) or re.fullmatch(r"-?\d+(\.\d+)?", s):
        return md_text(s)
    return md_code(s)


def _prop_rows(props, keys):
    """(label, value) rows for the given property keys; units merged into their value."""
    rows = []
    for key in keys:
        if key.endswith("_unit") and key[: -len("_unit")] in props:
            continue  # shown with its value
        if key.endswith("_map_unit_scale") and str(props.get(key, "")).startswith("3x:0,0,0,0,0,0"):
            continue
        value = fmt_value(props.get(key))
        unit = props.get(f"{key}_unit")
        if unit:
            value += f" {UNIT_WORDS.get(str(unit), md_text(unit))}"
        rows.append((PROP_LABELS.get(key, humanize(key)), value))
    return rows


def _dd_rows(dd_list):
    rows = []
    for dd in dd_list or []:
        source = (
            md_code(dd.get("expression"))
            if dd.get("expression")
            else f"field {md_code(dd.get('field'))}"
            if dd.get("field")
            else fmt_value(dd.get("value"))
        )
        rows.append((f"{humanize(dd.get('name'))} (data-defined)", source))
    return rows


def _image(path, alt):
    return f"![{md_text(alt or 'Symbol')}]({path})" if path else ""


# --------------------------------------------------------------------------- symbols


def _flat_symbol(symbol, prefix=""):
    """{ 'L1.color': value, ... } for diffing class symbols against a base symbol."""
    out = {}
    if not symbol:
        return out
    for i, layer in enumerate(symbol.get("layers") or [], 1):
        for k, v in (layer.get("properties") or {}).items():
            out[f"{prefix}L{i}.{k}"] = v
        if layer.get("sub_symbol"):
            out.update(_flat_symbol(layer["sub_symbol"], f"{prefix}L{i}.sub."))
    return out


def symbol_diff(base, other):
    """Readable list of what differs between two symbols ('Fill colour #8fb8de')."""
    a, b = _flat_symbol(base), _flat_symbol(other)
    parts = []
    for key in sorted(set(a) | set(b)):
        if a.get(key) == b.get(key) or key.endswith("_map_unit_scale"):
            continue
        prop = key.rsplit(".", 1)[-1]
        parts.append(f"{PROP_LABELS.get(prop, humanize(prop))} {fmt_value(b.get(key))}")
    if len((base or {}).get("layers") or []) != len((other or {}).get("layers") or []):
        parts.insert(0, "different number of symbol layers")
    return "; ".join(parts[:6]) + ("; ..." if len(parts) > 6 else "") if parts else "Same as first"


def symbol_details(doc, symbol, where, title="Symbol", depth=0):
    """Bold heading per symbol layer, then a Setting | Value | Where table of non-defaults."""
    if not symbol:
        return
    opacity = symbol.get("opacity")
    extra = f", opacity {round(opacity * 100)} %" if opacity is not None and opacity < 1 else ""
    doc.para(
        f"**{md_text(title)}:** {md_text(symbol.get('type'))} symbol with {len(symbol.get('layers') or [])} symbol layers{extra}."
    )
    for i, layer in enumerate(symbol.get("layers") or [], 1):
        name = layer.get("name") or layer.get("class")
        state = "" if layer.get("enabled", True) else " (disabled)"
        props = layer.get("properties") or {}
        rows = _prop_rows(props, layer.get("non_default") or [])
        rows += _dd_rows(layer.get("data_defined"))
        effect = layer.get("effect")
        if effect:
            inner = ", ".join(e["type"] for e in effect.get("effects", []) if e.get("enabled")) or effect["type"]
            rows.append(("Draw effects", md_text(inner)))
        label = f"{title} layer {i}: {name}{state}"
        if rows:
            doc.para(f"*{md_text(label)}*")
            doc.table(["Setting", "Value", "Where in QGIS"], [[r[0], r[1], f"{where} > {md_text(name)}"] for r in rows])
        else:
            doc.para(f"*{md_text(label)}*: all settings are QGIS defaults.")
        if layer.get("sub_symbol") and depth < 3:
            symbol_details(doc, layer["sub_symbol"], where, f"{title} layer {i} sub-symbol", depth + 1)


# --------------------------------------------------------------------------- renderers


def _scales(rule):
    lo, hi = rule.get("min_scale"), rule.get("max_scale")
    if not lo and not hi:
        return "All"
    return f"1:{int(lo):,} to 1:{int(hi):,}" if lo and hi else (f"up to 1:{int(lo):,}" if lo else f"from 1:{int(hi):,}")


def _flatten_rules(rules, path=()):
    for rule in rules or []:
        label = rule.get("label") or rule.get("description") or ("ELSE" if rule.get("else") else "(no label)")
        yield path + (label,), rule
        yield from _flatten_rules(rule.get("children"), path + (label,))


def vector_renderer(doc, renderer, where, depth=0):
    if not renderer:
        return
    rtype = renderer.get("type")
    name = renderer.get("name") or rtype
    where_r = f"{where} > {name}"
    intro = f"Renderer: **{md_text(name)}**"
    if renderer.get("attribute"):
        intro += f" on {md_code(renderer['attribute'])}"
    if renderer.get("classification"):
        intro += f", classification {md_text(renderer['classification'].get('name'))}"
    doc.para(intro + f". Where in QGIS: **{where_r}**.")

    settings = []
    props = renderer.get("properties") or {}
    for key in (
        "radius",
        "radius_unit",
        "quality",
        "max_value",
        "tolerance",
        "toleranceUnit",
        "placement",
        "symbollevels",
        "referencescale",
    ):
        if key in props and props[key] not in ("", "0", "-1") and not (key == "symbollevels" and props[key] == "0"):
            settings.append((humanize(key), fmt_value(props[key])))
    if renderer.get("weight_expression"):
        settings.append(("Weight", md_code(renderer["weight_expression"])))
    if renderer.get("order_by"):
        settings.append(("Control feature rendering order", md_code(renderer["order_by"])))
    if renderer.get("effect"):
        settings.append(("Layer effects", md_text(renderer["effect"]["type"])))
    if settings:
        doc.table(["Setting", "Value"], [[a, b] for a, b in settings])

    if renderer.get("categories"):
        cats = renderer["categories"]
        base = cats[0].get("symbol")
        doc.table(
            ["Symbol", "Value", "Legend", "Shown", "Symbol (vs first class)"],
            [
                [
                    _image(c.get("image"), f"Symbol for {c.get('label')}"),
                    fmt_value(c.get("value")) if c.get("value") not in ("", None) else "All other values",
                    md_text(c.get("label")),
                    "Yes" if c.get("render") else "No",
                    "Base symbol, below" if n == 0 else symbol_diff(base, c.get("symbol")),
                ]
                for n, c in enumerate(cats)
            ],
        )
        symbol_details(doc, base, where_r, "First class symbol")
    elif renderer.get("ranges"):
        ranges = renderer["ranges"]
        base = ranges[0].get("symbol")
        doc.table(
            ["Symbol", "From", "To", "Legend", "Symbol (vs first class)"],
            [
                [
                    _image(r.get("image"), f"Symbol for {r.get('label')}"),
                    fmt_number(r.get("lower")),
                    fmt_number(r.get("upper")),
                    md_text(r.get("label")) + ("" if r.get("render") else " (hidden)"),
                    "Base symbol, below" if n == 0 else symbol_diff(base, r.get("symbol")),
                ]
                for n, r in enumerate(ranges)
            ],
        )
        symbol_details(doc, base, where_r, "First class symbol")
    elif renderer.get("rules") is not None:
        flat = list(_flatten_rules(renderer["rules"]))
        base = next((r.get("symbol") for _p, r in flat if r.get("symbol")), None)
        doc.table(
            ["Symbol", "Rule", "Filter", "Scales", "Shown", "Symbol (vs first rule)"],
            [
                [
                    _image(r.get("image"), f"Symbol for rule {p[-1]}"),
                    md_text(" > ".join(p)),
                    "ELSE (all other features)" if r.get("else") else (md_code(r.get("filter")) or "All features"),
                    _scales(r),
                    "Yes" if r.get("active") else "No",
                    ""
                    if not r.get("symbol")
                    else ("Base symbol, below" if r.get("symbol") is base else symbol_diff(base, r.get("symbol"))),
                ]
                for p, r in flat
            ],
        )
        symbol_details(doc, base, where_r, "First rule symbol")
    elif renderer.get("symbol"):
        if renderer.get("image"):
            doc.para(_image(renderer["image"], "Layer symbol"))
        symbol_details(doc, renderer["symbol"], where_r)
    for key, title in (("cluster_symbol", "Cluster symbol"), ("center_symbol", "Center symbol")):
        if renderer.get(key):
            symbol_details(doc, renderer[key], where_r, title)
    for n, sym in enumerate(renderer.get("symbols") or [], 1):
        symbol_details(doc, sym, where_r, f"Symbol {n}")
    if renderer.get("embedded") and depth < 3:
        doc.para(f"**Embedded renderer** (the renderer used inside {md_text(name)}):")
        vector_renderer(doc, renderer["embedded"], where, depth + 1)


def raster_renderer(doc, renderer, legend, where):
    if not renderer:
        return
    name = renderer.get("name") or renderer.get("type")
    doc.para(f"Renderer: **{md_text(name)}**. Where in QGIS: **{where} > {md_text(name)}**.")
    props = renderer.get("properties") or {}
    rows = []
    for key in ("band", "min", "max", "interpolation", "classification_mode", "opacity"):
        if renderer.get(key) is not None and not (key == "opacity" and renderer[key] >= 1):
            rows.append((humanize(key), fmt_value(renderer[key])))
    for key in ("zfactor", "azimuth", "angle", "multidirection", "grayband", "gradient", "alphaBand", "nodataColor"):
        if key in props and props[key] not in ("", "-1"):
            rows.append((humanize(key), fmt_value(props[key])))
    if rows:
        doc.table(["Setting", "Value"], [[a, b] for a, b in rows])
    items = renderer.get("items") or []
    if items:
        images = [e.get("image") for e in legend] if len(legend) == len(items) else [None] * len(items)
        doc.table(
            ["Colour", "Value", "Hex", "Label"],
            [
                [
                    _image(img, f"Colour for {it.get('label') or it.get('value')}"),
                    fmt_number(it.get("value")),
                    md_code(it.get("color")),
                    md_text(it.get("label")),
                ]
                for img, it in zip(images, items)
            ],
        )
    pipe = renderer.get("pipe") or {}
    defaults = {
        "brightness": 0,
        "contrast": 0,
        "gamma": 1.0,
        "saturation": 0,
        "grayscale_mode": "GrayscaleOff",
        "colorize": False,
        "invert_colors": False,
        "zoomed_in_resampling": "nearest",
        "zoomed_out_resampling": "nearest",
        "max_oversampling": 2.0,
    }
    changed = [(humanize(k), fmt_value(v)) for k, v in pipe.items() if v is not None and defaults.get(k) != v]
    if changed:
        doc.para("Changed rendering settings (Layer Properties > Symbology > Layer Rendering / Resampling):")
        doc.table(["Setting", "Value"], [[a, b] for a, b in changed])


# --------------------------------------------------------------------------- labels


def _label_rows(settings):
    flat = settings.get("settings") or {}
    rows = []
    for key in settings.get("non_default") or []:
        if key in ("fieldName", "isExpression") or key.endswith("fieldName") or key.endswith("isExpression"):
            continue
        parts = key.split(".")
        tab = next(
            (LABEL_TABS[p.split("[")[0]] for p in reversed(parts[:-1]) if p.split("[")[0] in LABEL_TABS), "Labels"
        )
        value = flat.get(key)
        if _BOOL_KEY_RE.search(parts[-1]) and str(value).lower() in ("0", "1", "true", "false"):
            shown = "Yes" if str(value).lower() in ("1", "true") else "No"
        else:
            shown = fmt_value(value)
        rows.append((humanize(parts[-1]), shown, f"Layer Properties > Labels > {tab}"))
    for dd in settings.get("data_defined") or []:
        src = md_code(dd.get("expression")) if dd.get("expression") else f"field {md_code(dd.get('field'))}"
        rows.append((
            f"{humanize(dd.get('name'))} (data-defined)",
            src,
            "Layer Properties > Labels (data-defined override)",
        ))
    return rows


def labels(doc, labeling):
    if not labeling:
        return
    state = "on" if labeling.get("enabled") else "off"
    if labeling.get("settings"):
        s = labeling["settings"]
        source = (
            f"expression {md_code(s.get('field'))}" if s.get("is_expression") else f"field {md_code(s.get('field'))}"
        )
        doc.para(
            f"Labels are **{state}**: **Single Labels** using {source}. Where in QGIS: **Layer Properties > Labels**."
        )
        rows = _label_rows(s)
        if rows:
            doc.table(["Setting", "Value", "Where in QGIS"], [list(r) for r in rows])
    elif labeling.get("rules") is not None:
        flat = list(_flatten_rules(labeling["rules"]))
        doc.para(f"Labels are **{state}**: **Rule-based Labeling**. Where in QGIS: **Layer Properties > Labels**.")
        doc.table(
            ["Rule", "Filter", "Scales", "Active", "Label text"],
            [
                [
                    md_text(" > ".join(p)),
                    "ELSE" if r.get("else") else (md_code(r.get("filter")) or "All features"),
                    _scales(r),
                    "Yes" if r.get("active") else "No",
                    md_code((r.get("settings") or {}).get("field")) or "None",
                ]
                for p, r in flat
            ],
        )
        for p, r in flat:
            rows = _label_rows(r.get("settings") or {})
            if rows:
                doc.para(f"*Rule {md_text(' > '.join(p))}: changed settings*")
                doc.table(["Setting", "Value", "Where in QGIS"], [list(x) for x in rows])


# --------------------------------------------------------------------------- entry point


def style_chapter(doc, lyr):
    style = lyr.style
    if not style:
        return
    renderer = style.get("renderer")
    where = "Layer Properties > Symbology"
    doc.heading(4, "Symbology")
    if lyr.layer_type == "Raster":
        raster_renderer(doc, renderer, style.get("legend") or [], where)
    elif renderer:
        vector_renderer(doc, renderer, where)
        legend = style.get("legend") or []
        if legend and not (
            renderer.get("categories")
            or renderer.get("ranges")
            or renderer.get("rules") is not None
            or renderer.get("symbol")
        ):
            doc.table(
                ["Symbol", "Legend entry"],
                [[_image(e.get("image"), e.get("label")), md_text(e.get("label"))] for e in legend],
            )
    else:
        doc.para("No renderer.")
    if style.get("labeling"):
        doc.heading(4, "Labels")
        labels(doc, style["labeling"])
    named = style.get("named_styles") or {}
    if len(named.get("all") or []) > 1:
        doc.para(
            f"Named styles: {md_text(', '.join(named['all']))}; current {md_text(named.get('current'))}. "
            "Where in QGIS: **Layer Properties > Style > Style Manager**."
        )
    if style.get("qml"):
        doc.para(
            f"Style file: {md_code(style['qml'])}. To apply it, open **Layer Properties > Symbology**, "
            "choose **Style > Load Style** and select this file."
        )

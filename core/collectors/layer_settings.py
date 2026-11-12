# SPDX-License-Identifier: GPL-2.0-or-later
"""Elevation and the remaining layer and project settings, documented as "what differs from a
new layer (or project) in QGIS" and grouped by the dialog page where each is set.

Method: QGIS writes the layer's own XML (QgsMapLayer.writeLayerXml, so unsaved changes in the
open project count), and the same for a freshly created layer of the same kind (the reference
for QGIS defaults). Both are flattened (xmlwalk.flatten) and compared; only differences are
reported. Values are redacted structurally first (xmlwalk.redact_dom), as everywhere else.

Noise that is not a user setting is dropped: element ids and GUIDs, and the elevation-profile
symbols, whose colours QGIS picks at random for every new layer (summarised in one row).
"""

import os
import re
import tempfile

from qgis.core import (
    QgsMapLayerType,
    QgsProject,
    QgsRasterLayer,
    QgsReadWriteContext,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtXml import QDomDocument

from ..xmlwalk import option_value, redact_dom
from .common import safe_message

# Dialog page -> the <maplayer> child elements set there. Order = order in the report.
LAYER_PAGES = (
    ("Symbology", ("featureBlendMode",)),
    ("Rendering", ("selection", "pipe-data-defined-properties")),
    ("Transparency", ("noData",)),
    ("Temporal", ("temporal",)),
    ("Display", ("mapTip", "previewExpression")),
    ("Actions", ("attributeactions",)),
    (
        "Attributes Form",
        (
            "editform",
            "editforminit",
            "editforminitcodesource",
            "editforminitfilepath",
            "editforminitcode",
            "featformsuppress",
            "editorlayout",
            "editable",
            "labelOnTop",
            "reuseLastValuePolicy",
            "dataDefinedFieldProperties",
            "widgets",
        ),
    ),
    ("Attribute Table", ("attributetableconfig", "conditionalstyles", "storedexpressions")),
    ("Legend", ("legend",)),
    ("Digitizing", ("geometryOptions",)),
    ("Dependencies", ("dataDependencies", "layerDependencies")),
    ("Auxiliary Storage", ("auxiliaryLayer",)),
    ("Variables and custom properties", ("customproperties",)),
    ("Data Sources (Project Properties)", ("flags",)),
)
ELEVATION = "elevation"
LAYER_SECTIONS = tuple(t for _p, tags in LAYER_PAGES for t in tags) + (ELEVATION,)
# Project-level elements documented the same way, with the dialog where each is set.
PROJECT_PAGES = (
    ("Snapping Options", ("snapping-settings",)),
    ("View Settings and coordinate display (Project Properties)", ("ProjectDisplaySettings",)),
    ("Other project properties", ("properties",)),
)
PROJECT_SECTIONS = tuple(t for _p, tags in PROJECT_PAGES for t in tags)

_SKIP_TAGS = ("symbol", "data_defined_properties", "data-defined-properties")
_PROFILE_SYMBOLS = ("profileLineSymbol", "profileFillSymbol", "profileMarkerSymbol")
_GUID_RE = re.compile(r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$")
_ID_KEY_RE = re.compile(r"(^|[._@])(id|uuid|layerid|layer_id)$", re.IGNORECASE)
MAX_ROWS_PER_PAGE = 200


def _children_by_tag(el):
    out = {}
    child = el.firstChildElement()
    while not child.isNull():
        out.setdefault(child.tagName(), child)
        child = child.nextSiblingElement()
    return out


def _flat(el, skip=_SKIP_TAGS, prefix="", out=None, depth=0):
    """{dotted key: value} for attributes, decoded <Option> trees and leaf-element text."""
    out = {} if out is None else out
    if el is None or el.isNull() or depth > 40:
        return out
    named = el.tagName() == "properties" and el.hasAttribute("name")  # QGIS property tree node
    attrs = el.attributes()
    for i in range(attrs.count()):
        a = attrs.item(i).toAttr()
        if named and a.name() in ("name", "type"):
            continue  # the name is the key; the type is how QGIS stores it
        out[f"{prefix}@{a.name()}" if prefix else f"@{a.name()}"] = a.value()
    seen = {}
    child = el.firstChildElement()
    if child.isNull():
        text = el.text().strip()
        if text:
            out[prefix or "text"] = text
        return out
    while not child.isNull():
        tag = child.tagName()
        if tag not in skip:
            if tag == "Option":
                out[
                    f"{prefix}{child.attribute('name') or 'options'}"
                    if not prefix
                    else f"{prefix}.{child.attribute('name') or 'options'}"
                ] = option_value(child)
            else:
                if tag == "properties" and child.hasAttribute("name"):
                    tag = child.attribute("name")  # name the setting, not its position
                if tag in skip:
                    child = child.nextSiblingElement()
                    continue
                seen[tag] = seen.get(tag, 0) + 1
                key = tag if seen[tag] == 1 else f"{tag}[{seen[tag]}]"
                _flat(child, skip, f"{prefix}.{key}" if prefix else key, out, depth + 1)
        child = child.nextSiblingElement()
    return out


def _noise(key, value):
    if _ID_KEY_RE.search(key):
        return True
    return isinstance(value, str) and bool(_GUID_RE.match(value))


def _plain(value):
    """Option trees decode to dicts and lists: flatten them to dotted keys for a table."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            for sub, val in _plain(v).items():
                out[f"{k}.{sub}" if sub else str(k)] = val
        return out
    if isinstance(value, list):
        out = {}
        for i, v in enumerate(value, 1):
            for sub, val in _plain(v).items():
                out[f"{i}.{sub}" if sub else str(i)] = val
        return out
    return {"": "" if value is None else str(value)}


def _flat_plain(el, skip=_SKIP_TAGS):
    out = {}
    for key, value in _flat(el, skip).items():
        for sub, val in _plain(value).items():
            out[f"{key}.{sub}" if key and sub else (key or sub)] = val
    return out


# Known defaults the reference layer cannot show (a raster reference has no data source).
DEFAULT_OVERRIDES = {("noData", "noDataList@useSrcNoData"): "1"}


def diff_rows(section, el, ref_el, skip=_SKIP_TAGS):
    """Rows {section, setting, value, default} where `el` differs from the reference."""
    mine, ref = _flat_plain(el, skip), _flat_plain(ref_el, skip)
    rows = []
    for key in sorted(set(mine) | set(ref)):
        value, default = mine.get(key), DEFAULT_OVERRIDES.get((section, key), ref.get(key))
        if value == default or _noise(key, value) or (value in (None, "") and default in (None, "")):
            continue
        if value is None:  # present in a new layer, absent here: an entry the user removed
            value = ""
        rows.append({"section": section, "setting": key, "value": value, "default": default})
    return rows


def _profile_colours(el):
    colours = []
    for tag in _PROFILE_SYMBOLS:
        sym = el.firstChildElement(tag)
        if sym.isNull():
            continue
        for key, value in _flat_plain(sym, skip=("data_defined_properties",)).items():
            if key.endswith(("line_color", ".color")) and value and value not in colours:
                colours.append(value)
    return colours


def _layer_xml(layer, context):
    doc = QDomDocument()
    el = doc.createElement("maplayer")
    doc.appendChild(el)
    layer.writeLayerXml(el, doc, context)
    return doc, el


def _reference_layer(layer):
    """A new layer of the same kind, never opened from any data source."""
    if layer.type() == QgsMapLayerType.VectorLayer:
        geom = QgsWkbTypes.displayString(layer.wkbType()) if layer.isValid() else "Point"
        if not geom or geom in ("Unknown", "NoGeometry"):
            geom = "None"
        return QgsVectorLayer(f"{geom}?crs=EPSG:4326", "reference", "memory")
    if layer.type() == QgsMapLayerType.RasterLayer:
        return QgsRasterLayer("", "reference", "gdal")
    return None


def collect_layer_settings(project, model, options):
    """Fill each LayerDoc's `elevation` and `settings`, and model.project_settings."""
    context = QgsReadWriteContext()
    context.setPathResolver(project.pathResolver())
    by_id = {lyr.id: lyr for lyr in model.layers}
    references = {}
    for layer in project.mapLayers().values():
        doc_layer = by_id.get(layer.id())
        if doc_layer is None:
            continue
        try:
            doc, el = _layer_xml(layer, context)
            if options.redact:
                redact_dom(doc)
            key = (layer.type(), layer.wkbType() if layer.type() == QgsMapLayerType.VectorLayer else 0)
            if key not in references:
                ref = _reference_layer(layer)
                references[key] = _layer_xml(ref, context)[1] if ref is not None else None
            ref_el = references[key]
        except Exception as exc:  # reported per layer, never fatal
            model.add_problem("warning", "settings", f"Settings could not be read: {safe_message(exc)}", layer.id())
            continue
        mine = _children_by_tag(el)
        ref = _children_by_tag(ref_el) if ref_el is not None else {}
        pages = {}
        for page, tags in LAYER_PAGES:
            rows = []
            for tag in tags:
                if tag in mine or tag in ref:
                    rows += diff_rows(tag, mine.get(tag), ref.get(tag))
            if rows:
                pages[page] = rows[:MAX_ROWS_PER_PAGE]
        doc_layer.settings = pages
        elev = mine.get(ELEVATION)
        if elev is not None:
            rows = diff_rows(ELEVATION, elev, ref.get(ELEVATION), skip=_SKIP_TAGS + _PROFILE_SYMBOLS)
            doc_layer.elevation = {"rows": rows, "profile_colours": _profile_colours(elev)}
    _project_settings(project, model, options)


def _project_settings(project, model, options):
    path = project.fileName()
    if not path or not os.path.isfile(path):
        return
    from .tier_b import read_project_xml  # here: tier_b imports this module's section lists

    try:
        doc = QDomDocument()
        res = doc.setContent(read_project_xml(path))
        if not (res[0] if isinstance(res, tuple) else res):
            return
        if options.redact:
            redact_dom(doc)
        ref = _reference_project_xml()
    except Exception as exc:
        model.add_problem("warning", "settings", f"Project settings could not be compared: {safe_message(exc)}")
        return
    mine = _children_by_tag(doc.documentElement())
    theirs = _children_by_tag(ref.documentElement()) if ref is not None else {}
    pages = {}
    for page, tags in PROJECT_PAGES:
        rows = []
        for tag in tags:
            skip = _SKIP_TAGS + ("individual-layer-settings",)  # summarised below
            if tag == "properties":
                # Settings with their own chapters are not repeated here.
                skip += ("Variables", "Macros", "Paths", "Measure", "Measurement", "SpatialRefSys")
            rows += diff_rows(tag, mine.get(tag), theirs.get(tag), skip=skip)
        if tag == "snapping-settings" and tag in mine:
            ind = mine[tag].firstChildElement("individual-layer-settings")
            n = on = 0
            child = ind.firstChildElement() if not ind.isNull() else ind
            while not child.isNull():
                n += 1
                on += child.attribute("enabled") == "1"
                child = child.nextSiblingElement()
            if n:
                rows.append({
                    "section": tag,
                    "setting": "individual-layer-settings",
                    "value": f"{on} of {n} layers enabled (used only in Advanced Configuration mode)",
                    "default": None,
                })
        if rows:
            pages[page] = rows[:MAX_ROWS_PER_PAGE]
    model.project_settings = pages
    ann = mine.get("main-annotation-layer")
    if ann is not None:
        items = ann.firstChildElement("items")
        n = 0
        child = items.firstChildElement() if not items.isNull() else items
        while not child.isNull():
            n += 1
            child = child.nextSiblingElement()
        model.project_settings_summary = {"annotation_items": n}


_REF_PROJECT = None


def _reference_project_xml():
    """XML of a new, empty project (written once per session to a temporary folder)."""
    global _REF_PROJECT
    if _REF_PROJECT is None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "reference.qgs")
            ref = QgsProject()
            ref.write(path)
            doc = QDomDocument()
            with open(path, "rb") as fh:
                doc.setContent(fh.read())
            ref.clear()
        _REF_PROJECT = doc
    return _REF_PROJECT

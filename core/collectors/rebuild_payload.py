# SPDX-License-Identifier: GPL-2.0-or-later
"""The lossless rebuild payload in the JSON (docs/DESIGN.md section 8).

The saved project XML is the payload: it already holds every layer's style, every layout,
the layer tree, themes, relations and settings, so a rebuild from it loses nothing the
Tier A collectors do not understand. (The QML and QPT files written beside the report are
for people; the XML is the authority for programs.)

Three changes make it safe and portable:
- credentials are redacted structurally (xmlwalk.redact_dom), as everywhere else;
- each layer's data source is replaced by a marker (@docqgisproject:source/s1, a marker) and listed in
  a `sources` table, so a rebuilder can map paths and supply credentials per source;
  file sources record size and SHA-256 so the rebuilder can tell it found the same data;
- SVG and image files that styles and layouts use are embedded (base64, capped) with the
  exact reference string the XML uses, so the rebuilder can write them and repoint them.

Data themselves are never included (a non-goal of the design).
"""

import base64
import hashlib
import os

from qgis.core import QgsProviderRegistry
from qgis.PyQt.QtXml import QDomDocument

from ..safe_paths import sanitize_name
from ..schema import (
    MAX_RESOURCE_BYTES,
    MAX_RESOURCES,
    MAX_RESOURCES_TOTAL,
    REBUILD_FORMAT,
    RESOURCE_EXTENSIONS,
    SOURCE_MARKER,
)
from ..xmlwalk import redact_dom
from .common import DB_PROVIDERS, WEB_PROVIDERS, safe_message
from .tier_b import read_project_xml

MAX_HASH_BYTES = 512 * 1024 * 1024
_NOT_FILE_REF = ("base64:", "http://", "https://", ":/", "data:")


def _elements(node, depth=0):
    """Every element below node, depth-first (bounded)."""
    if depth > 200:
        return
    children = node.childNodes()
    for i in range(children.count()):
        el = children.at(i).toElement()
        if not el.isNull():
            yield el
            yield from _elements(el, depth + 1)


def _text(el):
    return el.text() if not el.isNull() else ""


def _set_text(el, value):
    children = el.childNodes()
    for i in reversed(range(children.count())):
        el.removeChild(children.at(i))
    el.appendChild(el.ownerDocument().createTextNode(value))


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_path(ref, project_dir):
    if not ref or ref.lower().startswith(_NOT_FILE_REF):
        return None
    return ref if os.path.isabs(ref) else os.path.normpath(os.path.join(project_dir, ref))


def _source_kind(provider, uri, path):
    if provider == "memory":
        return "memory"
    if provider in DB_PROVIDERS:
        return "database"
    if provider in WEB_PROVIDERS or "url=" in uri:
        return "web"
    if path:
        return "file"
    return "other"


def _file_info(path_as_written, project_dir, hashes):
    local = _local_path(path_as_written, project_dir)
    info = {"path": path_as_written, "exists": False, "size": None, "sha256": None}
    if local and os.path.isfile(local):
        info["exists"] = True
        info["size"] = os.path.getsize(local)
        if info["size"] <= MAX_HASH_BYTES:
            if local not in hashes:  # several layers often share one GeoPackage
                hashes[local] = _sha256(local)
            info["sha256"] = hashes[local]
    elif local and os.path.isdir(local):
        info["exists"] = True  # a folder source (e.g. a shapefile folder): no single hash
    return info


def _parameterise_sources(doc, project_dir, redact):
    """Replace each layer's datasource with a marker. Returns the sources table."""
    by_key, sources, marker_for_layer, hashes = {}, [], {}, {}
    root = doc.documentElement()
    for el in _elements(root):
        if el.tagName() != "maplayer":
            continue
        lid = _text(el.firstChildElement("id"))
        provider = _text(el.firstChildElement("provider")).strip()
        ds = el.firstChildElement("datasource")
        if not lid or ds.isNull():
            continue
        uri = _text(ds)
        key = (provider, uri)
        if key not in by_key:
            sid = f"s{len(sources) + 1}"
            try:
                parts = QgsProviderRegistry.instance().decodeUri(provider, uri) or {}
            except Exception:  # an exotic provider without a decoder
                parts = {}
            path = parts.get("path") if isinstance(parts.get("path"), str) else ""
            kind = _source_kind(provider, uri, path)
            entry = {
                "id": sid,
                "provider": provider or "unknown",
                "kind": kind,
                "uri": uri,
                "layer_ids": [],
                "redacted": "[REDACTED:" in uri,
                "file": _file_info(path, project_dir, hashes) if kind == "file" else None,
            }
            by_key[key] = entry
            sources.append(entry)
        entry = by_key[key]
        entry["layer_ids"].append(lid)
        marker = SOURCE_MARKER.format(id=entry["id"])
        marker_for_layer[lid] = (uri, marker)
        _set_text(ds, marker)
    # Layer-tree nodes (the main tree and layout legends) repeat the source in an attribute.
    for el in _elements(root):
        lid = el.attribute("id")
        if lid in marker_for_layer and el.hasAttribute("source"):
            uri, marker = marker_for_layer[lid]
            if el.attribute("source") == uri:
                el.setAttribute("source", marker)
    if not redact:
        for s in sources:
            s["redacted"] = False
    return sources


def _embed_resources(doc, project_dir, model):
    """Embed SVG and image files referenced by attribute or Option values."""
    refs = {}
    for el in _elements(doc.documentElement()):
        attrs = el.attributes()
        for j in range(attrs.count()):
            value = attrs.item(j).toAttr().value()
            if value.lower().endswith(RESOURCE_EXTENSIONS) and len(value) < 4096:
                refs.setdefault(value, None)
    resources, used_names, total, skipped = [], set(), 0, []
    for ref in sorted(refs):
        local = _local_path(ref, project_dir)
        if not local or not os.path.isfile(local):
            continue
        size = os.path.getsize(local)
        if size > MAX_RESOURCE_BYTES or total + size > MAX_RESOURCES_TOTAL or len(resources) >= MAX_RESOURCES:
            skipped.append(ref)
            continue
        with open(local, "rb") as fh:
            data = fh.read(MAX_RESOURCE_BYTES + 1)
        if len(data) != size:
            skipped.append(ref)  # changed while reading
            continue
        stem, ext = os.path.splitext(os.path.basename(local))
        name = sanitize_name(stem)[:100] + ext.lower()
        n = 2
        while name.lower() in used_names:
            name = f"{sanitize_name(stem)[:96]}-{n}{ext.lower()}"
            n += 1
        used_names.add(name.lower())
        total += size
        resources.append({
            "name": name,
            "ref": ref,
            "size": size,
            "sha256": hashlib.sha256(data).hexdigest(),
            "data_base64": base64.b64encode(data).decode("ascii"),
        })
    if skipped:
        model.add_problem(
            "warning",
            "rebuild",
            f"{len(skipped)} SVG or image files were not embedded in the JSON (larger than "
            f"{MAX_RESOURCE_BYTES // (1024 * 1024)} MB each or {MAX_RESOURCES_TOTAL // (1024 * 1024)} MB in total); "
            "a rebuild needs them supplied by hand.",
        )
    return resources


def collect_rebuild(project, model, options):
    """Fill model.rebuild from the saved project file."""
    path = project.fileName()
    if not path or not os.path.isfile(path):
        model.add_problem("info", "rebuild", "The project is not saved to a file; the JSON has no rebuild payload.")
        return
    try:
        data = read_project_xml(path)
        doc = QDomDocument()
        result = doc.setContent(data)
        ok = result[0] if isinstance(result, tuple) else bool(result)
        if not ok:
            raise ValueError("the project XML could not be parsed")
    except Exception as exc:  # reported, not fatal (principle 7)
        model.add_problem("warning", "rebuild", f"No rebuild payload: {safe_message(exc)}")
        return
    if options.redact:
        redact_dom(doc)  # the same secrets as elsewhere; not counted twice
    project_dir = os.path.dirname(os.path.abspath(path))
    sources = _parameterise_sources(doc, project_dir, options.redact)
    resources = _embed_resources(doc, project_dir, model)
    notes = []
    if any(s["redacted"] for s in sources):
        notes.append("Some sources had credentials removed; supply them at rebuild time (QGIS authentication).")
    model.rebuild = {
        "format": REBUILD_FORMAT,
        "project_file": os.path.basename(path),
        "qgis_version": doc.documentElement().attribute("version") or None,
        "project_xml": doc.toString(1),
        "sources": sources,
        "resources": resources,
        "notes": notes,
    }

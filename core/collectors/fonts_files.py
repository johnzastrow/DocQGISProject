# SPDX-License-Identifier: GPL-2.0-or-later
"""Fonts and external files used by the project (SVG, images), with whether they are
available on this machine. Missing ones are warnings: a rebuild elsewhere needs them.

Reads only the plain data already in the model (styling, layouts), so it adds no QGIS calls
beyond the installed-font list.
"""

import os

from qgis.PyQt.QtGui import QFontDatabase

# Symbol-layer properties that name a font or a file.
FONT_PROPS = {"font"}
FILE_PROPS = {"name": ("SvgMarker",), "svgFile": ("SVGFill",), "imageFile": ("RasterFill", "RasterMarker", "RasterLine")}


def _symbol_resources(symbol, where, fonts, files, depth=0):
    if not symbol or depth > 5:
        return
    for sl in symbol.get("layers") or []:
        props = sl.get("properties") or {}
        cls = sl.get("class")
        if cls == "FontMarker" and props.get("font"):
            fonts.setdefault(props["font"], set()).add(where)
        for key, classes in FILE_PROPS.items():
            value = props.get(key)
            if cls in classes and value and not str(value).startswith("base64:"):
                files.setdefault(str(value), set()).add(where)
        if sl.get("sub_symbol"):
            _symbol_resources(sl["sub_symbol"], where, fonts, files, depth + 1)


def _renderer_symbols(renderer):
    if not renderer:
        return
    for key in ("symbol", "cluster_symbol", "center_symbol"):
        if renderer.get(key):
            yield renderer[key]
    for c in (renderer.get("categories") or []) + (renderer.get("ranges") or []):
        if c.get("symbol"):
            yield c["symbol"]
    stack = list(renderer.get("rules") or [])
    while stack:
        rule = stack.pop()
        if rule.get("symbol"):
            yield rule["symbol"]
        stack.extend(rule.get("children") or [])
    yield from renderer.get("symbols") or []
    if renderer.get("embedded"):
        yield from _renderer_symbols(renderer["embedded"])


def _label_fonts(labeling):
    if not labeling:
        return
    settings = [labeling.get("settings")] if labeling.get("settings") else []
    stack = list(labeling.get("rules") or [])
    while stack:
        rule = stack.pop()
        if rule.get("settings"):
            settings.append(rule["settings"])
        stack.extend(rule.get("children") or [])
    for s in settings:
        family = (s.get("settings") or {}).get("text-style.fontFamily")
        if family:
            yield family


def resolve_path(path, project_dir):
    if not path or path.startswith(("http://", "https://")) or path.startswith(":/"):
        return None  # web or built-in resource: not a local file
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(project_dir or "", path))


def collect_resources(model, project_dir):
    fonts, files = {}, {}
    for lyr in model.layers:
        style = lyr.style or {}
        where = f"layer {lyr.name}"
        for sym in _renderer_symbols(style.get("renderer")):
            _symbol_resources(sym, where, fonts, files)
        for family in _label_fonts(style.get("labeling")):
            fonts.setdefault(family, set()).add(f"{where} labels")
    for lay in model.layouts:
        where = f"layout {lay.get('name')}"
        for item in lay.get("items") or []:
            d = item.get("details") or {}
            for key in ("font",):
                if isinstance(d.get(key), dict) and d[key].get("font_family"):
                    fonts.setdefault(d[key]["font_family"], set()).add(where)
            src = d.get("source")
            if isinstance(src, dict) and src.get("path") and not src.get("embedded"):
                files.setdefault(src["path"], set()).add(where)
            if d.get("symbol"):
                _symbol_resources(d["symbol"], where, fonts, files)

    installed = {f.lower() for f in QFontDatabase.families()}
    model.resources = {
        "fonts": [
            {"family": fam, "installed": fam.lower() in installed, "used_by": sorted(users)}
            for fam, users in sorted(fonts.items())
        ],
        "files": [],
    }
    for path, users in sorted(files.items()):
        local = resolve_path(path, project_dir)
        exists = os.path.exists(local) if local else None
        model.resources["files"].append({"path": path, "exists": exists, "used_by": sorted(users)})
        if exists is False:
            model.add_problem("warning", "resources", f"File {path} (used by {', '.join(sorted(users))}) was not found.")
    for f in model.resources["fonts"]:
        if not f["installed"]:
            model.add_problem(
                "warning", "resources",
                f"Font '{f['family']}' (used by {', '.join(f['used_by'])}) is not installed here; QGIS substitutes another font.",
            )

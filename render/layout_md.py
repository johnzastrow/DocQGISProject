# SPDX-License-Identifier: GPL-2.0-or-later
"""Markdown chapter for print layouts and reports (docs/DESIGN.md section 6).

Order inside each layout: rendered pages first, then the item list (position and size), then
item close-ups and per-item settings, tables, atlas, template file.
"""

from .style_md import fmt_value, humanize, symbol_details
from .text import fmt_bool, fmt_count, fmt_extent, fmt_number, md_code, md_text

WHERE_ITEM = "Layout > Item Properties"
TEMPLATE_STEPS = (
    "**Project > Layout Manager**, under *New from Template* choose *Specific*, select the file, then **Create**"
)


def _img(path, alt):
    return f"![{md_text(alt)}]({path})" if path else ""


def _pos(item):
    pos, size = item.get("position") or [None, None], item.get("size") or [None, None]
    unit = "mm" if item.get("units") in ("Millimeters", "LayoutMillimeters") else md_text(item.get("units"))
    p = f"{fmt_number(pos[0])}, {fmt_number(pos[1])} {unit}"
    if (item.get("details") or {}).get("auto_size"):
        return p, "sized to fit contents"
    return p, f"{fmt_number(size[0])} x {fmt_number(size[1])} {unit}"


def _notes(item):
    notes = []
    if item.get("rotation"):
        notes.append(f"rotated {fmt_number(item['rotation'])} degrees")
    if not item.get("visible", True):
        notes.append("hidden")
    if item.get("locked"):
        notes.append("locked")
    if item.get("exclude_from_exports"):
        notes.append("excluded from exports")
    if item.get("reference_point") not in (None, "UpperLeft"):
        notes.append(f"reference point {md_text(item['reference_point'])}")
    mf = (item.get("details") or {}).get("multiframe")
    if mf:
        notes.append(f"frame of {md_text(mf)}")
    if item.get("data_defined"):
        notes.append(f"{len(item['data_defined'])} data-defined")
    return "; ".join(notes)


def _common_rows(item):
    rows = []
    frame = item.get("frame") or {}
    if frame.get("enabled"):
        rows.append(("Frame", f"{md_code(frame.get('color'))}, {fmt_number(frame.get('width'))} mm", "Frame"))
    bg = item.get("background") or {}
    if bg.get("enabled"):
        rows.append(("Background", md_code(bg.get("color")), "Background"))
    if item.get("opacity") is not None and item["opacity"] < 1:
        rows.append(("Opacity", f"{round(item['opacity'] * 100)} %", "Rendering"))
    if item.get("blend_mode") not in (None, "SourceOver"):
        rows.append(("Blending mode", md_text(item["blend_mode"]), "Rendering"))
    for dd in item.get("data_defined") or []:
        src = md_code(dd.get("expression")) if dd.get("expression") else f"field {md_code(dd.get('field'))}"
        rows.append((f"{humanize(dd.get('name'))} (data-defined)", src, "Data defined override"))
    return rows


def _font(font):
    if not font:
        return "Not set"
    return f"{md_text(font.get('font_family'))} {fmt_number(font.get('size'))} pt, {md_code(font.get('color'))}"


def _detail_rows(item):
    d = item.get("details") or {}
    t = item.get("type")
    rows = []
    if t == "Map":
        rows += [
            ("Extent", fmt_extent(d.get("extent")), "Main Properties > Extents"),
            ("Scale", f"1:{fmt_number(round(d['scale']))}" if d.get("scale") else "Not set", "Main Properties > Scale"),
            ("CRS", md_code(d.get("crs")) or "Project CRS", "Main Properties > CRS"),
        ]
        if d.get("map_rotation"):
            rows.append(("Map rotation", f"{fmt_number(d['map_rotation'])} degrees", "Main Properties > Map rotation"))
        if d.get("follow_theme"):
            rows.append(("Follow map theme", md_text(d.get("theme")), "Layers > Follow map theme"))
        elif d.get("keep_layer_set"):
            rows.append(("Locked layers", md_text(", ".join(d.get("layers") or [])), "Layers > Lock layers"))
        if d.get("atlas_driven"):
            rows.append((
                "Controlled by atlas",
                f"{md_text(d.get('atlas_scaling'))}, margin {fmt_number(d.get('atlas_margin'))}",
                "Controlled by Atlas",
            ))
        for g in d.get("grids") or []:
            rows.append((
                f"Grid {md_text(g.get('name'))}",
                f"{md_text(g.get('style'))}, interval {fmt_number((g.get('interval') or [None])[0])} x "
                f"{fmt_number((g.get('interval') or [None, None])[1])}, annotations {fmt_bool(g.get('annotations'))}"
                + ("" if g.get("enabled") else " (disabled)"),
                "Grids",
            ))
        for ov in d.get("overviews") or []:
            rows.append((
                f"Overview {md_text(ov.get('name'))}",
                f"shows the extent of {md_text(ov.get('linked_map'))}",
                "Overviews",
            ))
    elif t == "Label":
        rows += [
            ("Text", md_code(d.get("text")), "Label > Main Properties"),
            ("Font", _font(d.get("font")), "Label > Appearance"),
            ("Alignment", f"{md_text(d.get('h_align'))}, {md_text(d.get('v_align'))}", "Label > Appearance"),
        ]
    elif t == "Legend":
        entries = ", ".join(e["name"] for e in d.get("entries") or [])
        rows += [
            ("Title", md_text(d.get("title")) or "None", "Legend > Main Properties"),
            ("Linked map", md_text(d.get("linked_map")) or "None", "Legend > Main Properties > Map"),
            (
                "Legend items",
                humanize(d["sync_mode"]) if d.get("sync_mode") else fmt_bool(d.get("auto_update")),
                "Legend > Legend Items",
            ),
            ("Entries", md_text(entries) or "None", "Legend > Legend Items"),
            ("Columns", fmt_number(d.get("columns")), "Legend > Columns"),
        ]
        if d.get("filter_by_map"):
            rows.append(("Only show items inside linked map", "Yes", "Legend > Legend Items"))
    elif t == "Scalebar":
        rows += [
            ("Style", md_text(d.get("style")), "Scalebar > Main Properties"),
            ("Linked map", md_text(d.get("linked_map")) or "None", "Scalebar > Main Properties > Map"),
            ("Units", f"{md_text(d.get('units'))}, label {md_code(d.get('unit_label')) or 'none'}", "Scalebar > Units"),
            (
                "Segments",
                f"{fmt_number(d.get('segments_left'))} left, {fmt_number(d.get('segments_right'))} right, "
                f"{fmt_number(d.get('units_per_segment'))} units each",
                "Scalebar > Segments",
            ),
            ("Font", _font(d.get("font")), "Scalebar > Fonts and Colors"),
        ]
    elif t == "Picture":
        src = d.get("source") or {}
        where = md_code(src.get("relative") or src.get("path")) if src else "None"
        if src.get("exists") is False:
            where += " (file not found)"
        rows += [
            ("Image source", where, "Picture > Main Properties"),
            ("Resize mode", md_text(d.get("resize_mode")), "Picture > Main Properties"),
        ]
        if d.get("north_arrow_map"):
            rows.append(("North arrow synchronised with", md_text(d["north_arrow_map"]), "Picture > Image Rotation"))
    elif t == "Shape":
        rows.append(("Shape", md_text(d.get("shape")), "Shape > Main Properties"))
        if d.get("corner_radius"):
            rows.append(("Corner radius", f"{fmt_number(d['corner_radius'])} mm", "Shape > Main Properties"))
    elif t in ("Polygon", "Polyline"):
        nodes = d.get("nodes") or []
        rows.append((
            "Nodes",
            md_text("; ".join(f"{fmt_number(x)}, {fmt_number(y)}" for x, y in nodes[:12]))
            + (" ..." if len(nodes) > 12 else ""),
            "Edit Nodes",
        ))
    elif t == "Group":
        rows.append(("Members", md_text(", ".join(m for m in d.get("members") or [] if m)), "Items panel"))
    elif t == "Chart":
        rows.append(("Source layer", md_text(d.get("source_layer")) or "None", "Chart > Main Properties"))
        for s in d.get("series") or []:
            rows.append((
                f"Series {md_text(s.get('name'))}",
                f"x {md_code(s.get('x'))}, y {md_code(s.get('y'))}",
                "Chart > Series",
            ))
    return rows


def _tables(doc, layout):
    for mf in layout.get("multiframes") or []:
        doc.para(f"*Table or frame: {md_text(mf.get('name'))} ({md_text(mf.get('type'))})*")
        rows = []
        if mf.get("layer") is not None or mf.get("source"):
            rows.append(("Source", f"{md_text(mf.get('source'))}: {md_text(mf.get('layer')) or 'None'}"))
        if mf.get("max_features") is not None:
            rows.append(("Maximum rows", fmt_number(mf.get("max_features"))))
        if mf.get("filter"):
            rows.append(("Filter", md_code(mf["filter"])))
        if mf.get("filter_to_atlas"):
            rows.append(("Only the current atlas feature", "Yes"))
        if mf.get("columns"):
            rows.append(("Columns", md_text(", ".join(f"{c['heading']} ({c['attribute']})" for c in mf["columns"]))))
        if mf.get("rows"):
            rows.append(("Cells", md_text(" / ".join(" | ".join(str(c) for c in row) for row in mf["rows"][:6]))))
        if mf.get("url"):
            rows.append(("URL", md_code(mf["url"])))
        rows.append(("Frames", md_text(", ".join(mf.get("frames") or [])) or "None"))
        doc.table(["Setting", "Value"], [list(r) for r in rows])


def _atlas(doc, atlas):
    if not atlas or not atlas.get("enabled"):
        return
    rows = [
        ("Coverage layer", md_text(atlas.get("coverage_layer")) or "None"),
        ("Hidden coverage layer", fmt_bool(atlas.get("hide_coverage"))),
        ("Page name", md_code(atlas.get("page_name")) or "Feature id"),
        ("Filter", md_code(atlas.get("filter")) or "None"),
        (
            "Sort by",
            (md_code(atlas.get("sort")) + (" ascending" if atlas.get("sort_ascending") else " descending"))
            if atlas.get("sort")
            else "None",
        ),
        ("Output file names", md_code(atlas.get("filename")) or "Default"),
    ]
    if atlas.get("feature_count") is not None:
        rows.append(("Features (pages)", fmt_number(atlas["feature_count"])))
    doc.para("*Atlas* (Where in QGIS: **Atlas > Atlas Settings**)")
    doc.table(["Setting", "Value"], [list(r) for r in rows])
    if atlas.get("first_page_image"):
        doc.para(_img(atlas["first_page_image"], "Atlas page for the first coverage feature"))


def _report(doc, layout):
    doc.para(
        f"A report with header {fmt_bool(layout.get('header')).lower()}, footer {fmt_bool(layout.get('footer')).lower()}. "
        "Where in QGIS: **Project > Layout Manager**, open the report, then **Report > Report Organizer**."
    )
    lines = []

    def walk(sections, depth):
        for s in sections:
            extra = f" grouped by {md_code(s.get('field'))} of {md_text(s.get('layer'))}" if s.get("field") else ""
            lines.append(f"{'  ' * depth}- {md_text(s.get('type'))} section{extra}")
            walk(s.get("children") or [], depth + 1)

    walk(layout.get("sections") or [], 0)
    doc.bullets(lines or ["- No sections."])


def layouts_chapter(doc, model):
    from .md_out import num

    n0 = num("layouts")
    doc.heading(2, f"{n0}. Print layouts")
    layouts = model.layouts or []
    if not layouts:
        doc.para("The project has no print layouts or reports.")
        return
    doc.para(
        f"{len(layouts)} layouts and reports. Each layout is saved as a template file you can load to recreate it, "
        f"then compare with the page images and settings below. To load a template: {TEMPLATE_STEPS}."
    )
    for n, lay in enumerate(layouts, 1):
        kind = "report" if lay.get("kind") == "report" else "print layout"
        doc.heading(3, f"{n0}.{n} {md_text(lay.get('name'))} ({kind})")
        if lay.get("template"):
            doc.para(f"Template file: {md_code(lay['template'])}.")
        if lay.get("kind") == "report":
            _report(doc, lay)
            continue
        pages = lay.get("pages") or []
        items = [i for i in lay.get("items") or [] if "error" not in i]
        frames = len(lay.get("multiframes") or [])
        doc.para(
            f"{fmt_count(len(pages), 'page')}, {fmt_count(len(items), 'item')}, "
            f"{fmt_count(frames, 'table or frame', 'tables or frames')}."
        )
        for p in pages:
            if p.get("image"):
                doc.para(_img(p["image"], f"Page {p['number']} of {lay.get('name')}"))
        doc.table(
            ["Page", "Size", "Orientation"],
            [
                [
                    str(p["number"]),
                    f"{fmt_number(p['size'][0])} x {fmt_number(p['size'][1])} mm",
                    md_text(p["orientation"]),
                ]
                for p in pages
            ],
        )
        if lay.get("variables"):
            doc.table(
                ["Layout variable", "Value"],
                [
                    [md_code(v["name"]), fmt_value(v["value"]) if not isinstance(v["value"], dict) else "*redacted*"]
                    for v in lay["variables"]
                ],
            )
        figures = getattr(doc, "figures", None)  # dialog screenshots, when the run took them
        if figures:
            figures("layout", ("Layout Designer",), target=lay.get("name"))
        doc.heading(4, "Items")
        doc.para("Items as listed in the Items panel (top first). Positions are from the top-left of their page.")
        doc.table(
            ["Item", "Type", "Page", "Position", "Size", "Notes"],
            [[md_text(i.get("name")), md_text(i.get("type")), str(i.get("page")), *_pos(i), _notes(i)] for i in items],
        )
        if doc.detail == "summary":
            _atlas(doc, lay.get("atlas"))
            continue
        doc.heading(4, "Item settings")
        for item in items:
            rows = _detail_rows(item) + _common_rows(item)
            sym = (item.get("details") or {}).get("symbol")
            page = f"Item: {item.get('name')}"
            shot = bool(figures) and page in doc.shots.pages_left("layout", target=lay.get("name"))
            if not rows and not item.get("image") and not sym and not shot:
                continue
            doc.heading(5, f"{md_text(item.get('name'))} ({md_text(item.get('type'))})")
            if item.get("image"):
                doc.para(_img(item["image"], f"Close-up of {item.get('name')}"))
            if shot:
                figures("layout", (page,), target=lay.get("name"))
            if rows:
                doc.table(["Setting", "Value", "Where in QGIS"], [[a, b, f"{WHERE_ITEM} > {c}"] for a, b, c in rows])
            if sym:
                symbol_details(doc, sym, f"{WHERE_ITEM} > Main Properties", f"{item.get('name')} symbol")
        _tables(doc, lay)
        _atlas(doc, lay.get("atlas"))

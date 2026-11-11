# SPDX-License-Identifier: GPL-2.0-or-later
"""Human output: the DocModel as a GitHub-flavoured Markdown report (docs/DESIGN.md section 6b).

Order follows how a person rebuilds a project: overview, "How to recreate this project",
then detail chapters, then problems. Settings are Setting | Value | Where in QGIS rows.
Every project-derived string goes through md_text() or md_code() (render/text.py).
Tables stay at 6 columns or fewer and headings at level 4 or above.
"""

from .strings import WHERE, add_layer_hint
from .layout_md import TEMPLATE_STEPS, layouts_chapter
from .style_md import style_chapter
from .text import (
    fmt_bool,
    fmt_extent,
    fmt_number,
    fmt_redacted_or_text,
    fmt_scale,
    md_code,
    md_text,
)

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


class _Doc:
    """Tiny Markdown builder that keeps blank lines between blocks."""

    def __init__(self, detail="standard"):
        self.lines = []
        self.detail = detail  # summary | standard | full

    def block(self, *lines):
        if self.lines and self.lines[-1] != "":
            self.lines.append("")
        self.lines.extend(lines)
        self.lines.append("")

    def heading(self, level, text):
        self.block("#" * level + " " + text)

    def para(self, text):
        self.block(text)

    def table(self, header, rows):
        if not rows:
            return
        head = "| " + " | ".join(header) + " |"
        sep = "|" + "|".join("---" for _ in header) + "|"
        body = ["| " + " | ".join(cell if cell != "" else " " for cell in row) + " |" for row in rows]
        self.block(head, sep, *body)

    def bullets(self, items):
        if items:
            self.block(*items)

    def text(self):
        return "\n".join(self.lines).rstrip() + "\n"


def _settings(doc, rows):
    """A Setting | Value | Where in QGIS table; rows are (label, value_markdown, where_key)."""
    doc.table(["Setting", "Value", "Where in QGIS"], [[label, value, WHERE.get(key, "")] for label, value, key in rows])


def _layer_names(model):
    return {lyr.id: lyr.name for lyr in model.layers}


def _source_location(lyr):
    """Where the data are, for a person: relative path when possible, else the redacted URI."""
    src = lyr.source
    if src.path_relative:
        loc = md_code(src.path_relative)
    elif src.path:
        loc = md_code(src.path)
    else:
        loc = md_code(src.uri)
    table = src.parts.get("layerName") if isinstance(src.parts, dict) else None
    if table:
        loc += f", layer {md_code(table)}"
    return loc


# --------------------------------------------------------------------------- chapters


def _overview(doc, model):
    p = model.project
    n_vec = sum(1 for lyr in model.layers if lyr.layer_type == "Vector")
    n_ras = sum(1 for lyr in model.layers if lyr.layer_type == "Raster")
    n_other = len(model.layers) - n_vec - n_ras
    groups = _count_groups(model.layer_tree)
    doc.heading(2, f"{num('overview')}. Overview")
    summary = (
        f"This project has {len(model.layers)} layers ({n_vec} vector, {n_ras} raster"
        + (f", {n_other} other" if n_other else "")
        + f") in {groups} groups, {len(model.relations)} relations, {len(model.themes)} map themes "
        f"and {len(model.bookmarks)} bookmarks."
    )
    doc.para(summary)
    if p.overview_image:
        doc.para(f"![Overview map of the visible layers]({p.overview_image})")
    crs = p.crs
    doc.table(
        ["Item", "Value"],
        [
            ["Title", md_text(p.title) or "Not set"],
            ["Project file", md_code(p.file_name) or "Not saved"],
            ["Saved with QGIS", md_text(p.qgis_version_saved) or "Unknown"],
            ["Last saved", md_text(p.saved_at) or "Unknown"],
            ["Project CRS", _crs_text(crs)],
            ["Layers", fmt_number(len(model.layers))],
        ],
    )


def _count_groups(node):
    if node is None:
        return 0
    return sum((1 if c.kind == "group" else 0) + _count_groups(c) for c in node.children)


def _crs_text(crs):
    if crs is None or not crs.valid:
        return "Not set"
    return f"{md_code(crs.authid)} {md_text(crs.description)}".strip()


def _recreate(doc, model):
    p = model.project
    names = _layer_names(model)
    by_id = {lyr.id: lyr for lyr in model.layers}
    doc.heading(2, f"{num('recreate')}. How to recreate this project")
    doc.para(
        "Follow these steps in a new QGIS project. Each step names the QGIS menu to use; "
        "the detail chapters below list every setting."
    )
    steps = [
        "Create a new project: **Project > New**.",
        f"Set the project CRS to {_crs_text(p.crs)}: **{WHERE['project_crs']}**.",
        f"Set *Save paths* to **{md_text(p.path_storage or 'Relative')}** and the title to "
        f"**{md_text(p.title) or 'Not set'}**: **Project > Properties > General**.",
    ]
    for item in _tree_steps(model.layer_tree, by_id, names):
        steps.append(item)
    if model.variables:
        steps.append(f"Add the project variables in chapter {num('variables')}: **{WHERE['variables']}**.")
    if model.relations:
        steps.append(f"Create the relations in chapter {num('relations')}: **{WHERE['relations']}**.")
    if model.themes:
        steps.append(
            f"Create each map theme in chapter {num('themes')}: show only the listed layers, then **{WHERE['themes']} > Add Theme**."
        )
    if model.bookmarks:
        steps.append(f"Add the bookmarks in chapter {num('bookmarks')}: **{WHERE['bookmarks']}**.")
    for lay in model.layouts or []:
        if lay.get("template"):
            kind = "report" if lay.get("kind") == "report" else "print layout"
            if kind == "report":
                steps.append(
                    f"Create the report **{md_text(lay.get('name'))}**: **Project > Layout Manager**, choose "
                    f"*Empty Report*, **Create**, then add its sections as listed in chapter {num('layouts')} "
                    f"(full definition for reference: {md_code(lay['template'])})."
                )
            else:
                steps.append(
                    f"Create the print layout **{md_text(lay.get('name'))}** from {md_code(lay['template'])}: {TEMPLATE_STEPS}."
                )
    steps.append("Save the project: **Project > Save As**.")
    doc.bullets([f"{n}. {s}" for n, s in enumerate(steps, 1)])


def _tree_steps(node, by_id, names, path=()):
    """One step per group and per layer, in layer-tree order (top of the panel first)."""
    out = []
    if node is None:
        return out
    for child in node.children:
        where = f" inside group **{md_text(path[-1])}**" if path else ""
        if child.kind == "group":
            extra = " Make it a mutually exclusive group." if child.mutually_exclusive else ""
            vis = "" if child.visible else " Uncheck it (hidden)."
            out.append(f"Add a group **{md_text(child.name)}**{where}.{extra}{vis}")
            out.extend(_tree_steps(child, by_id, names, path + (child.name,)))
        else:
            lyr = by_id.get(child.layer_id)
            if lyr is None:
                out.append(f"Layer **{md_text(child.name)}**{where}: not found in the project.")
                continue
            hint = add_layer_hint(lyr.source.provider, lyr.source.parts)
            vis = "" if child.visible else " Uncheck it (hidden)."
            qml = (lyr.style or {}).get("qml")
            style = (
                f" Load its style from {md_code(qml)} (**Layer Properties > Symbology > Style > Load Style**)."
                if qml
                else ""
            )
            out.append(
                f"Add layer **{md_text(lyr.name)}** from {_source_location(lyr)} with **{hint}**{where}.{style}{vis}"
            )
    return out


def _project_settings(doc, model):
    p = model.project
    doc.heading(2, f"{num('settings')}. Project settings")
    doc.para("General project properties. Colours are shown as hexadecimal RGB.")
    rows = [
        ("Title", md_text(p.title) or "Not set", "project_title"),
        ("Save paths", md_text(p.path_storage), "path_storage"),
        ("Project home", md_code(p.home_path) if p.home_path else "Default (project folder)", "project_home"),
        ("Project CRS", _crs_text(p.crs), "project_crs"),
        ("Ellipsoid", md_code(p.ellipsoid) or "Not set", "ellipsoid"),
        ("Distance units", md_text(p.distance_units), "distance_units"),
        ("Area units", md_text(p.area_units), "area_units"),
        ("Background colour", md_code(p.background_color), "background_color"),
        ("Selection colour", md_code(p.selection_color), "selection_color"),
        ("Full extent", fmt_extent(p.default_view_extent) if p.default_view_extent else "Not set", "view_extent"),
        ("Python macros", f"Present, {p.macro_lines} lines (not run)" if p.has_macros else "None", "macros"),
    ]
    _settings(doc, rows)
    if p.transform_operations:
        doc.heading(3, "Datum transformations")
        doc.table(
            ["Source CRS", "Destination CRS", "Operation"],
            [
                [md_code(t["source"]), md_code(t["destination"]), md_code(t["operation"])]
                for t in p.transform_operations
            ],
        )
    md = p.metadata or {}
    if any(md.get(k) for k in ("title", "abstract", "author", "keywords")):
        doc.heading(3, "Project metadata")
        kw = md.get("keywords") or {}
        _settings(
            doc,
            [
                ("Title", md_text(md.get("title")) or "Not set", "project_metadata"),
                ("Abstract", md_text(md.get("abstract")) or "Not set", "project_metadata"),
                ("Author", md_text(md.get("author")) or "Not set", "project_metadata"),
                ("Created", md_text(md.get("created")) or "Not set", "project_metadata"),
                (
                    "Keywords",
                    "; ".join(f"{md_text(k)}: {md_text(', '.join(v))}" for k, v in kw.items()) or "None",
                    "project_metadata",
                ),
            ],
        )


def _layer_tree(doc, model):
    doc.heading(2, f"{num('tree')}. Layer tree")
    doc.para(
        "The Layers panel from top to bottom. [x] is checked (visible), [ ] is unchecked. "
        "A layer inside an unchecked group is not drawn."
    )
    lines = []

    def walk(node, depth):
        for child in node.children:
            mark = "[x]" if child.visible else "[ ]"
            indent = "  " * depth
            if child.kind == "group":
                tags = []
                if child.mutually_exclusive:
                    tags.append("mutually exclusive")
                if not child.expanded:
                    tags.append("collapsed")
                if child.embedded:
                    tags.append("embedded")
                tag = f" ({', '.join(tags)})" if tags else ""
                lines.append(f"{indent}- {mark} Group **{md_text(child.name)}**{tag}")
                walk(child, depth + 1)
            else:
                lines.append(f"{indent}- {mark} {md_text(child.name)}")

    if model.layer_tree is not None:
        walk(model.layer_tree, 0)
    doc.bullets(lines or ["The layer tree is empty."])


def _fields_table(doc, lyr):
    rows = []
    for f in lyr.fields:
        notes = []
        if f.origin and f.origin not in ("Provider", "Unknown"):
            notes.append(f"origin: {md_text(f.origin.lower())}")
        if f.expression:
            notes.append(f"expression {md_code(f.expression)}")
        if f.default_expression:
            notes.append(f"default {md_code(f.default_expression)}")
        if f.not_null:
            notes.append("not null")
        if f.unique:
            notes.append("unique")
        if f.constraint_expression:
            notes.append(f"constraint {md_code(f.constraint_expression)}")
        type_text = md_text(f.type_name or f.variant_type)
        if f.length:
            type_text += f" ({f.length}" + (f", {f.precision}" if f.precision else "") + ")"
        rows.append([
            str(f.index),
            md_code(f.name),
            type_text,
            md_text(f.alias),
            "; ".join(notes),
            md_text(f.widget_type),
        ])
    doc.table(["#", "Name", "Type", "Alias", "Notes", "Widget"], rows)


def _layers(doc, model):
    doc.heading(2, f"{num('layers')}. Layers")
    doc.para(
        f"Each layer in layer-tree order. Data-source credentials are "
        f"{'redacted' if model.options.get('redact', True) else 'NOT redacted'}."
    )
    names = _layer_names(model)
    for n, lyr in enumerate(model.layers, 1):
        doc.heading(3, f"{num('layers')}.{n} {md_text(lyr.name)}")
        src = lyr.source
        state = "loaded" if lyr.data_loaded else ("not contacted (remote)" if src.remote else "not loaded")
        rows = [
            ("Layer name", md_text(lyr.name), "layer_name"),
            (
                "Type",
                md_text(lyr.layer_type) + (f", {md_text(lyr.wkb_type)}" if lyr.data_loaded and lyr.wkb_type else ""),
                "layer_info",
            ),
            ("Data provider", md_code(src.provider), "layer_info"),
            ("Data source", _source_location(lyr), "layer_info"),
            ("Data status", state, "layer_info"),
            (
                "CRS",
                _crs_text(lyr.crs) if lyr.data_loaded or (lyr.crs and lyr.crs.valid) else "Unknown (data not loaded)",
                "layer_crs",
            ),
        ]
        if lyr.feature_count is not None:
            rows.append(("Feature count", fmt_number(lyr.feature_count), "layer_info"))
        if lyr.extent:
            rows.append(("Extent", fmt_extent(lyr.extent), "layer_info"))
        if lyr.subset_string:
            rows.append(("Filter", md_code(lyr.subset_string), "subset"))
        if lyr.scale_visibility:
            sv = lyr.scale_visibility
            rows.append((
                "Visible between scales",
                f"{fmt_scale(sv.get('min_scale'))} (out) and {fmt_scale(sv.get('max_scale'))} (in)",
                "scale_visibility",
            ))
        if lyr.opacity is not None and lyr.opacity < 1:
            rows.append(("Opacity", f"{round(lyr.opacity * 100)} %", "opacity"))
        if lyr.blend_mode and lyr.blend_mode != "SourceOver":
            rows.append(("Blending mode", md_text(lyr.blend_mode), "blend_mode"))
        if lyr.raster:
            r = lyr.raster
            rows.append((
                "Raster size",
                f"{fmt_number(r.get('width'))} x {fmt_number(r.get('height'))} pixels, "
                f"{fmt_number(r.get('band_count'))} bands",
                "layer_info",
            ))
            if r.get("data_type"):
                rows.append(("Data type", md_text(r["data_type"]), "layer_info"))
        if lyr.title:
            rows.append(("Metadata title", md_text(lyr.title), "layer_metadata"))
        if lyr.abstract:
            rows.append(("Abstract", md_text(lyr.abstract), "layer_metadata"))
        if lyr.notes:
            rows.append(("Notes", md_text(lyr.notes), "notes"))
        _settings(doc, rows)

        if lyr.thumbnail:
            doc.para(f"![{md_text(lyr.name)} on its own]({lyr.thumbnail})")
        style_chapter(doc, lyr)

        if isinstance(src.parts, dict) and len(src.parts) > 1 and doc.detail != "summary":
            doc.heading(4, "Source parameters")
            # Show the project-relative path instead of an absolute one when there is one.
            part_rows = [
                [
                    md_code(k),
                    md_code(src.path_relative) if k == "path" and src.path_relative else fmt_redacted_or_text(v),
                ]
                for k, v in sorted(src.parts.items())
                if v not in (None, "", [], {})
            ]
            doc.table(["Parameter", "Value"], part_rows)
        if lyr.fields:
            doc.heading(4, "Fields")
            doc.para(
                f"{len(lyr.fields)} fields. Where in QGIS: **{WHERE['fields']}**; widgets: **{WHERE['widgets']}**."
            )
            _fields_table(doc, lyr)
        if lyr.joins:
            doc.heading(4, "Joins")
            doc.para(f"Where in QGIS: **{WHERE['joins']}**.")
            doc.table(
                ["Join layer", "Join field", "Target field", "Prefix", "Fields", "Cached"],
                [
                    [
                        md_text(j.join_layer_name or names.get(j.join_layer_id) or j.join_layer_id),
                        md_code(j.join_field),
                        md_code(j.target_field),
                        md_code(j.prefix) if j.prefix else "Default",
                        md_text(", ".join(j.fields_subset)) if j.fields_subset else "All",
                        fmt_bool(j.cached),
                    ]
                    for j in lyr.joins
                ],
            )


def _relations(doc, model):
    doc.heading(2, f"{num('relations')}. Relations")
    if not model.relations:
        doc.para("The project has no relations.")
        return
    doc.para(f"Where in QGIS: **{WHERE['relations']}**. The parent is the referenced layer.")
    doc.table(
        ["Name", "Parent layer", "Child layer", "Fields (child = parent)", "Strength"],
        [
            [
                md_text(r.name),
                md_text(r.referenced_layer_name or r.referenced_layer_id),
                md_text(r.referencing_layer_name or r.referencing_layer_id),
                ", ".join(f"{md_code(fp['referencing'])} = {md_code(fp['referenced'])}" for fp in r.field_pairs),
                md_text(r.strength) + ("" if r.valid else " (invalid)"),
            ]
            for r in model.relations
        ],
    )


def _variables(doc, model):
    doc.heading(2, f"{num('variables')}. Project variables")
    if not model.variables:
        doc.para("The project defines no variables of its own.")
        return
    doc.para(
        f"Variables defined in this project (QGIS built-in variables are not listed). Where in QGIS: **{WHERE['variables']}**."
    )
    doc.table(["Name", "Value"], [[md_code(v.name), fmt_redacted_or_text(v.value)] for v in model.variables])


def _themes(doc, model):
    doc.heading(2, f"{num('themes')}. Map themes")
    if not model.themes:
        doc.para("The project has no map themes.")
        return
    doc.para(
        f"Each theme lists the layers it shows; all other layers are hidden. Where in QGIS: **{WHERE['themes']}**."
    )
    doc.table(
        ["Theme", "Visible layers", "Pinned styles"],
        [
            [
                md_text(t.name),
                ", ".join(md_text(tl.layer_name or tl.layer_id) for tl in t.layers) or "None",
                ", ".join(f"{md_text(tl.layer_name)}: {md_text(tl.style)}" for tl in t.layers if tl.style) or "None",
            ]
            for t in model.themes
        ],
    )


def _bookmarks(doc, model):
    doc.heading(2, f"{num('bookmarks')}. Spatial bookmarks")
    if not model.bookmarks:
        doc.para("The project has no spatial bookmarks.")
        return
    doc.para(f"Where in QGIS: **{WHERE['bookmarks']}**.")
    doc.table(
        ["Name", "Group", "Extent", "CRS"],
        [[md_text(b.name), md_text(b.group) or "None", fmt_extent(b.extent), md_code(b.crs)] for b in model.bookmarks],
    )


def _problems(doc, model):
    doc.heading(2, f"{num('problems')}. Warnings and problems")
    if not model.problems:
        doc.para("No problems were found.")
        return
    doc.para("Errors mean a part could not be read; warnings need attention when rebuilding.")
    names = _layer_names(model)
    items = []
    for p in sorted(model.problems, key=lambda p: _SEVERITY_ORDER.get(p.severity, 9)):
        where = f" (layer {md_text(names.get(p.layer_id, p.layer_id))})" if p.layer_id else ""
        items.append(f"- **{md_text(p.severity.capitalize())}**, {md_text(p.section)}{where}: {md_text(p.message)}")
    doc.bullets(items)


# --------------------------------------------------------------------------- entry point


def render_markdown(model):
    doc = _Doc(detail=(model.options or {}).get("detail", "standard"))
    p = model.project
    title = p.title or p.file_name or "Untitled project"
    doc.heading(1, f"Project documentation: {md_text(title)}")
    gen = model.generator or {}
    doc.para(
        f"Generated by DocQGISProject {md_text(gen.get('plugin_version', ''))} with QGIS "
        f"{md_text(gen.get('qgis_version', ''))} on {md_text(gen.get('generated_at', ''))}."
    )
    if not model.options.get("redact", True):
        doc.para("**WARNING: credential redaction was turned off. This report may contain passwords or keys.**")
    elif model.redactions:
        total = sum(model.redactions.values())
        kinds = ", ".join(f"{md_text(k)} ({v})" for k, v in sorted(model.redactions.items()))
        doc.para(f"Credentials removed from this report: {total} ({kinds}).")
    doc.bullets([f"- {n}. {title}" for n, (_key, title, _fn) in enumerate(CHAPTERS, 1)])
    for _key, _title, chapter in CHAPTERS:
        chapter(doc, model)
    return doc.text()


def _resources(doc, model):
    doc.heading(2, f"{num('resources')}. Fonts and files")
    res = model.resources or {}
    fonts, files = res.get("fonts") or [], res.get("files") or []
    if not fonts and not files:
        doc.para("The styles and layouts use no named fonts or external files.")
        return
    doc.para(
        "Fonts and files the styles and layouts need. Install missing fonts and copy missing files before "
        "rebuilding, or QGIS substitutes a font or draws nothing."
    )
    if fonts:
        doc.table(
            ["Font", "Installed here", "Used by"],
            [[md_text(f["family"]), fmt_bool(f["installed"]), md_text(", ".join(f["used_by"]))] for f in fonts],
        )
    if files:
        doc.table(
            ["File", "Found", "Used by"],
            [
                [
                    md_code(f["path"]),
                    "Yes" if f["exists"] else ("No" if f["exists"] is False else "Not a local file"),
                    md_text(", ".join(f["used_by"])),
                ]
                for f in files
            ],
        )


def _coverage(doc, model):
    doc.heading(2, f"{num('coverage')}. Appendix: coverage of the project file")
    cov = model.coverage or {}
    if not cov:
        doc.para("No coverage figures: the project file could not be read (see the problems chapter).")
        return
    doc.para(
        f"The chapters above explain {cov['percent_claimed']} % of the elements in the project file "
        f"({fmt_number(cov['claimed_elements'])} of {fmt_number(cov['total_elements'])}). The rest is listed "
        "below by section. The JSON file holds every element; the QML and QPT files hold the complete styles "
        "and layouts."
    )
    groups = cov.get("unclaimed_groups") or []
    if groups:
        doc.table(
            ["Project file section not explained above", "Elements", "Distinct paths"],
            [[md_code(g["group"]), fmt_number(g["elements"]), fmt_number(g["paths"])] for g in groups[:60]],
        )
    if doc.detail != "full":
        doc.para("Run with the *full* detail level to list every unexplained element with sample values.")
        return
    doc.heading(3, f"{num('coverage')}.1 Unexplained elements (Tier B)")
    doc.para(
        "Each path is an element of the project file, with how often it occurs and sample attribute values (redacted)."
    )
    rows = []
    for e in model.tier_b or []:
        sample = "; ".join(f"{k}={v}" for k, v in (e["samples"][0] if e["samples"] else {}).items())
        if not sample and e.get("text"):
            sample = e["text"]
        rows.append([md_code(e["path"]), fmt_number(e["count"]), md_code(sample[:160]) if sample else ""])
    doc.table(["Path", "Count", "Example"], rows)


# Chapter order. Numbers in headings, the contents list and cross-references all derive from it.
def _source_status(src):
    if src["kind"] == "file":
        info = src.get("file") or {}
        if info.get("exists") is False:
            return "file missing"
        return "file found" + (f", {fmt_number(info['size'])} bytes" if info.get("size") is not None else "")
    if src.get("redacted"):
        return "needs credentials"
    return "no action needed" if src["kind"] == "memory" else "check access"


def _rebuild(doc, model):
    doc.heading(2, f"{num('rebuild')}. Appendix: rebuilding from the JSON")
    rb = model.rebuild
    if not rb:
        doc.para(
            "This run has no rebuild data. It is written with the JSON output, and only for a project saved to a file."
        )
        return
    doc.para(
        "The JSON file holds the complete project file, so a program can rebuild the project from it. "
        "Credentials are not in it. Data are not in it either: the rebuilt project points at the same data sources."
    )
    doc.para(
        "To rebuild, open the QGIS Python console, import "
        + md_code("rebuild_project")
        + " from "
        + md_code("DocQGISProject.core.rebuild")
        + " and call it with this JSON file and a new .qgz file name. "
        + "If the data have moved, pass "
        + md_code("source_map")
        + ", which maps an old folder to a new one. "
        + "For a source that needs a login, pass "
        + md_code("auth_map")
        + ", which maps the source (such as s3) to a QGIS authentication configuration. "
        + "The rebuilder never overwrites a file, and it removes macros and other Python code."
    )
    rows = []
    for src in rb.get("sources") or []:
        info = src.get("file") or {}
        where = info.get("path") if src["kind"] == "file" and info.get("path") else src["uri"]
        rows.append([
            md_code(src["id"]),
            md_code(src["provider"]),
            src["kind"],
            fmt_number(len(src["layer_ids"])),
            md_code(where[:120] + ("..." if len(where) > 120 else "")) if where else "",
            _source_status(src),
        ])
    if rows:
        doc.table(["Source", "Provider", "Kind", "Layers", "Location", "Status"], rows)
    files = rb.get("resources") or []
    if files:
        doc.para(
            f"{fmt_number(len(files))} SVG or image files are embedded in the JSON and written beside the new project."
        )


CHAPTERS = [
    ("overview", "Overview", _overview),
    ("recreate", "How to recreate this project", _recreate),
    ("settings", "Project settings", _project_settings),
    ("tree", "Layer tree", _layer_tree),
    ("layers", "Layers", _layers),
    ("layouts", "Print layouts", layouts_chapter),
    ("relations", "Relations", _relations),
    ("variables", "Project variables", _variables),
    ("themes", "Map themes", _themes),
    ("bookmarks", "Spatial bookmarks", _bookmarks),
    ("resources", "Fonts and files", _resources),
    ("problems", "Warnings and problems", _problems),
    ("coverage", "Appendix: coverage of the project file", _coverage),
    ("rebuild", "Appendix: rebuilding from the JSON", _rebuild),
]


def num(key):
    """Chapter number for a chapter key."""
    return next(n for n, (k, _t, _f) in enumerate(CHAPTERS, 1) if k == key)

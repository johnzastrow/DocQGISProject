# SPDX-License-Identifier: GPL-2.0-or-later
"""Human output: the DocModel as a GitHub-flavoured Markdown report (docs/DESIGN.md section 6b).

Order follows how a person rebuilds a project: overview, "How to recreate this project",
then detail chapters, then problems. Settings are Setting | Value | Where in QGIS rows.
Every project-derived string goes through md_text() or md_code() (render/text.py).
Tables stay at 6 columns or fewer and headings at level 4 or above.
"""

from .strings import WHERE, add_layer_hint
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

    def __init__(self):
        self.lines = []

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
    doc.heading(2, "1. Overview")
    summary = (
        f"This project has {len(model.layers)} layers ({n_vec} vector, {n_ras} raster"
        + (f", {n_other} other" if n_other else "")
        + f") in {groups} groups, {len(model.relations)} relations, {len(model.themes)} map themes "
        f"and {len(model.bookmarks)} bookmarks."
    )
    doc.para(summary)
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
    doc.heading(2, "2. How to recreate this project")
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
        steps.append(f"Add the project variables in chapter 7: **{WHERE['variables']}**.")
    if model.relations:
        steps.append(f"Create the relations in chapter 6: **{WHERE['relations']}**.")
    if model.themes:
        steps.append(
            f"Create each map theme in chapter 8: show only the listed layers, then **{WHERE['themes']} > Add Theme**."
        )
    if model.bookmarks:
        steps.append(f"Add the bookmarks in chapter 9: **{WHERE['bookmarks']}**.")
    steps.append("Save the project: **Project > Save As**.")
    doc.bullets([f"{n}. {s}" for n, s in enumerate(steps, 1)])
    doc.para("*Not yet documented by this development build:* print layouts (phase P3).")


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
    doc.heading(2, "3. Project settings")
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
    doc.heading(2, "4. Layer tree")
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
    doc.heading(2, "5. Layers")
    doc.para(
        f"Each layer in layer-tree order. Data-source credentials are "
        f"{'redacted' if model.options.get('redact', True) else 'NOT redacted'}."
    )
    names = _layer_names(model)
    for n, lyr in enumerate(model.layers, 1):
        doc.heading(3, f"5.{n} {md_text(lyr.name)}")
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

        style_chapter(doc, lyr)

        if isinstance(src.parts, dict) and len(src.parts) > 1:
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
    doc.heading(2, "6. Relations")
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
    doc.heading(2, "7. Project variables")
    if not model.variables:
        doc.para("The project defines no variables of its own.")
        return
    doc.para(
        f"Variables defined in this project (QGIS built-in variables are not listed). Where in QGIS: **{WHERE['variables']}**."
    )
    doc.table(["Name", "Value"], [[md_code(v.name), fmt_redacted_or_text(v.value)] for v in model.variables])


def _themes(doc, model):
    doc.heading(2, "8. Map themes")
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
    doc.heading(2, "9. Spatial bookmarks")
    if not model.bookmarks:
        doc.para("The project has no spatial bookmarks.")
        return
    doc.para(f"Where in QGIS: **{WHERE['bookmarks']}**.")
    doc.table(
        ["Name", "Group", "Extent", "CRS"],
        [[md_text(b.name), md_text(b.group) or "None", fmt_extent(b.extent), md_code(b.crs)] for b in model.bookmarks],
    )


def _problems(doc, model):
    doc.heading(2, "10. Warnings and problems")
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
    doc = _Doc()
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
    doc.bullets([
        "- 1. Overview",
        "- 2. How to recreate this project",
        "- 3. Project settings",
        "- 4. Layer tree",
        "- 5. Layers",
        "- 6. Relations",
        "- 7. Project variables",
        "- 8. Map themes",
        "- 9. Spatial bookmarks",
        "- 10. Warnings and problems",
    ])
    for chapter in (
        _overview,
        _recreate,
        _project_settings,
        _layer_tree,
        _layers,
        _relations,
        _variables,
        _themes,
        _bookmarks,
        _problems,
    ):
        chapter(doc, model)
    return doc.text()

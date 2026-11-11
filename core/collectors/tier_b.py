# SPDX-License-Identifier: GPL-2.0-or-later
"""Tier B: a generic walk of the project XML, the coverage report and the appendix of
everything the Tier A chapters do not explain (docs/DESIGN.md section 5).

Claims are declared per Tier A area as tag paths below the <qgis> root:
- SUBTREE claims cover an element and everything inside it;
- ELEMENT claims cover an element and its attributes, not its children.
Coverage = share of XML elements claimed. Unclaimed paths are listed so "complete" is a number.

Safety: the XML is parsed with Qt's parser (bounded entity expansion, no external entities),
never with xml.etree/minidom; a .qgz is read in memory with a size cap; every value is redacted
structurally (xmlwalk.redact_dom) before it is recorded.
"""

import os
import zipfile

from qgis.PyQt.QtXml import QDomDocument

from ..xmlwalk import attributes, redact_dom
from .common import safe_message

MAX_PROJECT_XML_BYTES = 200 * 1024 * 1024
MAX_SAMPLES = 3
MAX_VALUE_CHARS = 120
ML = "projectlayers/maplayer"

SUBTREE_CLAIMS = {
    # project (collectors/project.py)
    "title",
    "projectCrs",
    "homePath",
    "projectMetadata",
    "transformContext",
    "ProjectViewSettings",
    "relations",
    "visibility-presets",
    "Bookmarks",
    "properties/Variables",
    "properties/Macros",
    "properties/Paths",
    "properties/Measure",
    "properties/Measurement",
    # layer tree (collectors/layers.py)
    "layer-tree-group",
    "layerorder",
    # layers (collectors/layers.py)
    f"{ML}/id",
    f"{ML}/datasource",
    f"{ML}/layername",
    f"{ML}/provider",
    f"{ML}/srs",
    f"{ML}/extent",
    f"{ML}/wgs84extent",
    f"{ML}/layerOpacity",
    f"{ML}/blendMode",
    f"{ML}/resourceMetadata",
    f"{ML}/aliases",
    f"{ML}/defaults",
    f"{ML}/constraints",
    f"{ML}/constraintExpressions",
    f"{ML}/expressionfields",
    f"{ML}/fieldConfiguration",
    f"{ML}/vectorjoins",
    f"{ML}/keywordList",
    # styling (collectors/styling.py)
    f"{ML}/renderer-v2",
    f"{ML}/labeling",
    f"{ML}/pipe",
    f"{ML}/map-layer-style-manager",
    # layouts (collectors/layouts.py)
    "Layouts",
}
ELEMENT_CLAIMS = {"", "projectlayers", ML, "properties"}


def _claimed(path):
    if path in ELEMENT_CLAIMS:
        return True
    return any(path == c or path.startswith(c + "/") for c in SUBTREE_CLAIMS)


def read_project_xml(path):
    """The project XML text from a .qgs, or the .qgs inside a .qgz (read in memory, capped)."""
    if path.lower().endswith(".qgz"):
        with zipfile.ZipFile(path) as zf:
            members = [m for m in zf.infolist() if m.filename.lower().endswith(".qgs") and "/" not in m.filename]
            if not members:
                raise ValueError("no .qgs file inside the .qgz archive")
            member = members[0]
            if member.file_size > MAX_PROJECT_XML_BYTES:
                raise ValueError("project XML is larger than the 200 MB limit")
            with zf.open(member) as fh:
                data = fh.read(MAX_PROJECT_XML_BYTES + 1)
    else:
        if os.path.getsize(path) > MAX_PROJECT_XML_BYTES:
            raise ValueError("project XML is larger than the 200 MB limit")
        with open(path, "rb") as fh:
            data = fh.read(MAX_PROJECT_XML_BYTES + 1)
    if len(data) > MAX_PROJECT_XML_BYTES:
        raise ValueError("project XML is larger than the 200 MB limit")
    return data


def _walk(el, path, stats, depth=0):
    if depth > 200:
        return
    entry = stats.setdefault(path, {"count": 0, "attributes": set(), "samples": []})
    entry["count"] += 1
    attrs = attributes(el)
    entry["attributes"].update(attrs)
    if attrs and len(entry["samples"]) < MAX_SAMPLES:
        entry["samples"].append({
            k: (v[:MAX_VALUE_CHARS] + "...") if len(v) > MAX_VALUE_CHARS else v for k, v in attrs.items()
        })
    nodes = el.childNodes()
    text = ""
    for i in range(nodes.count()):
        child = nodes.at(i)
        if child.isElement():
            c = child.toElement()
            # Project settings are nested <properties name="X"> elements: name the path
            # segment after X so claims such as "properties/Variables" can match.
            seg = (
                c.attribute("name") if c.tagName() == "properties" and path and c.hasAttribute("name") else c.tagName()
            )
            _walk(c, f"{path}/{seg}" if path else seg, stats, depth + 1)
        elif child.isText() or child.isCDATASection():
            text += child.toCharacterData().data()
    text = text.strip()
    if text and "text" not in entry and len(entry["samples"]) <= MAX_SAMPLES:
        entry["text"] = (text[:MAX_VALUE_CHARS] + "...") if len(text) > MAX_VALUE_CHARS else text


def collect_tier_b(project, model, options):
    """Fill model.coverage (always) and model.tier_b (detail == "full")."""
    path = project.fileName()
    if not path or not os.path.isfile(path):
        model.add_problem("info", "coverage", "The project is not saved to a file; the coverage report was skipped.")
        return
    if project.isDirty():
        model.add_problem(
            "info", "coverage", "The project has unsaved changes; the coverage report reflects the saved file."
        )
    try:
        data = read_project_xml(path)
        doc = QDomDocument()
        result = doc.setContent(data)
        ok = result[0] if isinstance(result, tuple) else bool(result)
        if not ok:
            raise ValueError("the project XML could not be parsed")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        model.add_problem("warning", "coverage", f"Coverage report skipped: {safe_message(exc)}")
        return
    if options.redact:
        redact_dom(doc)  # same secrets as elsewhere; not added to the totals again

    stats = {}
    root = doc.documentElement()
    # Paths are relative to the <qgis> root ("" is the root itself).
    _walk(root, "", stats)
    total = sum(e["count"] for e in stats.values())
    claimed = sum(e["count"] for p, e in stats.items() if _claimed(p))
    groups = {}
    for p, e in stats.items():
        if _claimed(p):
            continue
        parts = p.split("/")
        top = "/".join(parts[:3]) if p.startswith(ML + "/") else parts[0]
        g = groups.setdefault(top, {"group": top, "elements": 0, "paths": 0})
        g["elements"] += e["count"]
        g["paths"] += 1
    model.coverage = {
        "total_elements": total,
        "claimed_elements": claimed,
        "percent_claimed": round(100.0 * claimed / total, 1) if total else 0.0,
        "unclaimed_groups": sorted(groups.values(), key=lambda g: (-g["elements"], g["group"])),
    }
    if options.detail == "full":
        model.tier_b = [
            {
                "path": p,
                "count": e["count"],
                "attributes": sorted(e["attributes"]),
                "samples": e["samples"],
                "text": e.get("text"),
            }
            for p, e in sorted(stats.items())
            if not _claimed(p)
        ]

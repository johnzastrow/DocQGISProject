"""Layouts chapter on a hand-built model: structure, escaping, readability."""

from core.model import DocModel
from render.md_out import render_markdown

from ..readability import lint_markdown


def _layout():
    return {
        "name": "Main <draft>",
        "kind": "print_layout",
        "template": "layouts/01_Main.qpt",
        "pages": [{"number": 1, "size": [297.0, 210.0], "units": "Millimeters", "orientation": "landscape",
                   "image": "layouts/01_Main/page_01.png"}],
        "variables": [{"name": "api_token", "value": {"redacted": "token"}}],
        "items": [
            {"name": "main map", "type": "Map", "page": 1, "position": [10.0, 20.0], "size": [180.0, 150.0],
             "units": "Millimeters", "reference_point": "UpperLeft", "visible": True, "rotation": 0,
             "details": {"extent": [0, 0, 1, 1], "scale": 25000.0, "crs": "EPSG:32619", "grids": [], "overviews": [],
                         "follow_theme": True, "theme": "Zones | only"},
             "frame": {"enabled": True, "color": "#000000", "width": 0.3}, "image": "layouts/01_Main/item_map.png"},
            {"name": "legend", "type": "Legend", "page": 1, "position": [200.0, 85.0], "size": [0.0, 0.0],
             "units": "Millimeters", "visible": True,
             "details": {"auto_size": True, "sync_mode": "AllProjectLayers", "entries": [{"name": "zones"}]}},
        ],
        "multiframes": [{"name": "<Attribute table frame>", "type": "Attribute Table", "source": "LayerAttributes",
                         "layer": "zones", "max_features": 5, "columns": [{"heading": "Name", "attribute": "name"}],
                         "frames": ["<Attribute table frame>"]}],
        "atlas": {"enabled": True, "coverage_layer": "zones", "page_name": '"name"', "feature_count": 9,
                  "first_page_image": "layouts/01_Main/atlas_first_page.png"},
    }


def test_layout_chapter():
    m = DocModel()
    m.options = {"redact": True}
    m.layouts = [_layout(), {"name": "Zone report", "kind": "report", "template": "layouts/02_Zone_report.xml",
                             "header": False, "footer": False,
                             "sections": [{"type": "FieldGroup", "field": "zone", "layer": "zones", "children": []}]}]
    text = render_markdown(m)
    assert lint_markdown(text) == []
    assert "## 6. Print layouts" in text and "## 7. Relations" in text
    assert "### 6.1 Main &lt;draft> (print layout)" in text
    assert "![Page 1 of Main &lt;draft>](layouts/01_Main/page_01.png)" in text
    assert "| legend | Legend | 1 | 200, 85 mm | sized to fit contents |" in text
    assert "Zones \\| only" in text
    assert "*redacted*" in text and "api_token" in text
    assert "Create the print layout **Main &lt;draft>** from `layouts/01_Main.qpt`" in text
    assert "Create the report **Zone report**" in text and "grouped by `zone`" in text

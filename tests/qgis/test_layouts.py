"""P3 acceptance: every layout item type in the fixtures is documented with position and size
and rendered; page and item images; QPT saved and loadable; atlas and report documented;
known QGIS crashers are avoided, not hit."""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readability import lint_markdown  # noqa: E402


@pytest.fixture(scope="module")
def layouts(plugin_pkg, fixtures_dir, tmp_path_factory):
    from DocQGISProject.core.runner import document_project

    out = tmp_path_factory.mktemp("layout_out")
    document_project(str(fixtures_dir / "layout.qgz"), str(out))
    data = json.loads((out / "project.json").read_text(encoding="utf-8"))
    md = (out / "report.md").read_text(encoding="utf-8")
    by_name = {lay["name"]: lay for lay in data["semantic"]["layouts"]}
    return data, md, by_name, out


def _items(layout):
    return {i["name"]: i for i in layout["items"]}


def _ink(path):
    """Share of sampled pixels that are not near-white (a blank render scores about 0)."""
    from qgis.PyQt.QtGui import QImage

    img = QImage(str(path))
    total = dark = 0
    for y in range(0, img.height(), 5):
        for x in range(0, img.width(), 5):
            c = img.pixelColor(x, y)
            total += 1
            dark += c.red() < 235 or c.green() < 235 or c.blue() < 235
    return dark / max(total, 1)


def test_report_is_readable_and_images_exist(layouts):
    data, md, _by, out = layouts
    assert lint_markdown(md) == []
    linked = re.findall(r"\]\(((?:images|layouts)/[^)]+)\)", md)
    assert linked and all((out / rel).is_file() for rel in linked)
    assert not [p for p in data["problems"] if p["severity"] == "error"], data["problems"]


def test_every_registered_item_type_is_documented(layouts):
    from qgis.core import QgsApplication

    _d, _md, by_name, _out = layouts
    zoo = by_name["Item zoo"]
    seen = {i["type"] for i in zoo["items"]} | {m["type"] for m in zoo["multiframes"]}
    registered = set(QgsApplication.layoutItemRegistry().itemTypes().values()) - {"Page"}
    assert registered <= seen, registered - seen
    for item in zoo["items"]:
        assert item["position"] is not None and item["size"] is not None, item["name"]
        assert item["properties"], f"{item['name']} has no XML properties"


def test_main_layout_items(layouts):
    _d, _md, by_name, out = layouts
    main = by_name["Main"]
    items = _items(main)
    assert main["pages"][0]["size"] == [297.0, 210.0] and main["pages"][0]["orientation"] == "landscape"
    m = items["main map"]
    assert (m["position"], m["size"], m["units"]) == ([10.0, 20.0], [180.0, 150.0], "Millimeters")
    md_ = m["details"]
    assert not md_["empty_extent"] and md_["grids"][0]["interval"] == [1000.0, 1000.0]
    inset = items["inset map"]["details"]
    assert inset["follow_theme"] and inset["theme"] == "Zones only"
    assert inset["overviews"][0]["linked_map"] == "main map"
    assert [e["name"] for e in items["legend"]["details"]["entries"]] == ["sites", "trails", "zones"]
    assert items["scale bar"]["details"]["linked_map"] == "main map"
    pic = items["north arrow"]["details"]["source"]
    assert pic["exists"] and pic["relative"] == "./assets/north.svg"
    assert len(items["triangle"]["details"]["nodes"]) == 3
    assert items["marker"]["details"]["symbol"]["layers"]
    assert main["variables"] == [{"name": "map_author", "value": "Fixture cartographer"}]
    tables = {mf["type"]: mf for mf in main["multiframes"]}
    assert tables["Attribute Table"]["layer"] == "zones" and tables["Attribute Table"]["max_features"] == 5
    assert tables["Fixed Table"]["rows"][1] == ["CRS", "EPSG:32619"]


def test_page_and_item_images_show_content(layouts):
    _d, _md, by_name, out = layouts
    main = by_name["Main"]
    assert _ink(out / main["pages"][0]["image"]) > 0.15
    close_up = _items(main)["main map"]["image"]
    assert close_up and _ink(out / close_up) > 0.3  # an empty map frame scores about 0.05
    assert _items(main)["legend"]["image"] and _items(main)["scale bar"]["image"]


def test_atlas_and_report(layouts):
    _d, _md, by_name, out = layouts
    atlas = by_name["Atlas by zone"]["atlas"]
    assert atlas["enabled"] and atlas["coverage_layer"] == "zones" and atlas["feature_count"] == 9
    assert atlas["page_name"] == '"name"' and atlas["filename"] == "'zone_' || \"id\""
    assert (out / atlas["first_page_image"]).is_file()
    assert _items(by_name["Atlas by zone"])["Map 1"]["details"]["atlas_driven"]
    report = by_name["Zone report"]
    assert report["kind"] == "report"
    assert report["sections"][0]["type"] == "FieldGroup" and report["sections"][0]["field"] == "zone"


def test_templates_load_back(layouts, fixtures_dir):
    from qgis.core import QgsPrintLayout, QgsProject, QgsReadWriteContext
    from qgis.PyQt.QtXml import QDomDocument

    _d, _md, by_name, out = layouts
    project = QgsProject()
    assert project.read(str(fixtures_dir / "layout.qgz"))
    main = by_name["Main"]
    assert main["template"].endswith(".qpt")
    doc = QDomDocument()
    assert doc.setContent((out / main["template"]).read_text(encoding="utf-8"))[0]
    assert doc.documentElement().tagName() == "Layout"
    rebuilt = QgsPrintLayout(project)
    _items_loaded, ok = rebuilt.loadFromTemplate(doc, QgsReadWriteContext())
    assert ok
    names = {i.displayName() for i in rebuilt.items() if hasattr(i, "displayName")}
    assert {"main map", "inset map", "legend", "scale bar", "title"} <= names
    assert by_name["Zone report"]["template"].endswith(".xml")


def test_crashing_chart_is_skipped_not_rendered(layouts):
    data, _md, by_name, _out = layouts
    zoo = by_name["Item zoo"]
    assert zoo["pages"][0]["image"] is None  # the page holding the source-less chart
    assert any("zoo Chart" in p["message"] and "crash" in p["message"] for p in data["problems"])


def test_thumbnails_and_overview(layouts):
    data, _md, _by, out = layouts
    sem = data["semantic"]
    assert sem["project"]["overview_image"] and _ink(out / sem["project"]["overview_image"]) > 0.3
    for lyr in sem["layers"]:
        assert lyr["thumbnail"] and (out / lyr["thumbnail"]).is_file(), lyr["name"]


def test_layouts_off_images(plugin_pkg, fixtures_dir, tmp_path):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project

    document_project(str(fixtures_dir / "layout.qgz"), str(tmp_path), DocOptions(images=False))
    data = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert all(p["image"] is None for lay in data["semantic"]["layouts"] for p in lay.get("pages", []))
    assert all(lay["template"] for lay in data["semantic"]["layouts"])  # templates still saved

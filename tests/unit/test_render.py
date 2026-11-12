"""Renderers on a hand-built model: escaping, readability lint, strict JSON."""

import json

import pytest

from core.model import CrsDoc, DocModel, FieldDoc, LayerDoc, Problem, ProjectDoc, SourceDoc, TreeNode, VariableDoc
from core.options import DocOptions
from render.json_out import render_json
from render.md_out import render_markdown
from render.text import fmt_count, md_code, md_text

from ..readability import lint_markdown

HOSTILE = "<script>alert(1)</script> | *b* [l](http://x) `c` _u_ &lt;"


def _model():
    m = DocModel()
    m.generator = {"plugin_version": "0.1.0-dev", "qgis_version": "4.2", "generated_at": "2026-11-11T00:00:00+00:00"}
    m.options = DocOptions().to_dict()
    m.project = ProjectDoc(
        title=HOSTILE, file_name="p.qgz", path_storage="Relative", crs=CrsDoc("EPSG:4326", "WGS 84", True)
    )
    lyr = LayerDoc(
        id="l1",
        name=HOSTILE,
        layer_type="Vector",
        valid=True,
        data_loaded=True,
        source=SourceDoc(
            provider="ogr",
            uri="./d.gpkg|layername=t",
            parts={"path": "/x/d.gpkg", "layerName": "t"},
            path="/x/d.gpkg",
            path_relative="./d.gpkg",
        ),
        fields=[FieldDoc(0, "a|b", type_name="String", expression="\"a\" || '|'", origin="Expression")],
        extent=[0.0, 0.0, 1.0, float("nan")],
    )
    m.layers.append(lyr)
    m.layer_tree = TreeNode("group", "", children=[TreeNode("layer", HOSTILE, layer_id="l1")])
    m.variables.append(VariableDoc("api_key", {"redacted": "api_key"}))
    m.problems.append(Problem("warning", "layers", HOSTILE, "l1"))
    return m


def test_md_text_neutralises_markup():
    out = md_text(HOSTILE)
    assert "<script" not in out and "&lt;script" in out
    assert "\\|" in out and "\\*b\\*" in out and "\\[l\\]" in out and "\\`c\\`" in out
    assert "&amp;lt;" in out


def test_md_code_handles_backticks_and_pipes():
    assert md_code("a`b") == "``a`b``"
    assert md_code("x|y") == "`x\\|y`"
    assert md_code("`start") == "`` `start ``"


def test_markdown_passes_lint_and_escapes():
    text = render_markdown(_model())
    assert lint_markdown(text) == []
    assert "<script" not in text
    assert "*redacted (api\\_key)*" in text or "*redacted (api_key)*" in text
    for n in range(1, 11):
        assert f"## {n}. " in text


def test_markdown_without_redaction_has_banner():
    m = _model()
    m.options["redact"] = False
    assert "redaction was turned off" in render_markdown(m)


def test_json_is_strict_and_structured():
    data = json.loads(render_json(_model()))
    assert data["schema"] == "docqgisproject/1"
    assert set(data) == {
        "schema",
        "generator",
        "options",
        "semantic",
        "rebuild",
        "screenshots",
        "problems",
        "redactions",
        "coverage",
        "tier_b",
    }
    lyr = data["semantic"]["layers"][0]
    assert lyr["extent"][3] is None  # NaN became null
    assert data["semantic"]["variables"][0]["value"] == {"redacted": "api_key"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"formats": ("json", "docx")},
        {"formats": ()},
        {"detail": "everything"},
        {"redact": "yes"},
        {"image_dpi": 10},
        {"image_dpi": 120.5},
        {"image_dpi": True},
        {"images": 1},
        {"embed_resources": "no"},
        {"screenshot_pages": "some"},
        {"qml_folder": None},
        {"qml_folder": "/x\x00y"},
        {"screenshots": "desktop"},
        {"screenshots": "layers"},  # needs screenshot_layers
        {"screenshots": "layers", "screenshot_layers": ("",)},
        {"screenshots": "layers", "screenshot_layers": (1,)},
        {"screenshots": "all", "screenshot_layers": tuple(f"l{i}" for i in range(201))},
    ],
)
def test_options_reject_invalid(kwargs):
    with pytest.raises(ValueError):
        DocOptions(**kwargs).validate()


def test_options_screenshot_layers_round_trip():
    o = DocOptions(screenshots="layers", screenshot_layers=["a", "b"]).validate()
    assert o.screenshot_layers == ("a", "b")
    assert o.to_dict()["screenshot_layers"] == ["a", "b"]


def test_rebuild_appendix():
    m = _model()
    m.rebuild = {
        "format": "qgis-project-xml/1",
        "project_file": "p.qgz",
        "project_xml": "<qgis/>",
        "sources": [
            {
                "id": "s1",
                "provider": "ogr",
                "kind": "file",
                "uri": "./a.gpkg|layername=a",
                "layer_ids": ["l1"],
                "redacted": False,
                "file": {"path": "./a.gpkg", "exists": False, "size": None, "sha256": None},
            },
            {
                "id": "s2",
                "provider": "postgres",
                "kind": "database",
                "uri": "dbname='g' user='[REDACTED:user]' " + HOSTILE,
                "layer_ids": ["l2", "l3"],
                "redacted": True,
                "file": None,
            },
        ],
        "resources": [],
    }
    md = render_markdown(m)
    section = md[md.index("Appendix: rebuilding from the JSON") :]
    assert "| `s1` | `ogr` | file | 1 | `./a.gpkg` | file missing |" in section
    assert "needs credentials" in section
    assert lint_markdown(md) == []
    m.rebuild = None
    assert "This run has no rebuild data" in render_markdown(m)


def test_screenshot_appendix():
    m = _model()
    assert "No dialog screenshots" in render_markdown(m)
    layer_id = m.layers[0].id
    m.screenshots = {
        "environment": {"QGIS": "4.2.3", "Style": "Fusion"},
        "items": [
            {"kind": "project", "target": "project", "page": "General", "image": "images/screenshots/project_01.png"},
            {
                "kind": "project",
                "target": "project",
                "page": "Data Sources",
                "image": None,
                "skipped": "it lists data sources",
            },
            {
                "kind": "layer",
                "target": HOSTILE,
                "target_id": layer_id,
                "page": "Symbology",
                "image": "images/screenshots/layer_001_01.png",
                "masked": 2,
            },
            {
                "kind": "layer",
                "target": HOSTILE,
                "target_id": layer_id,
                "page": "Rendering",
                "image": "images/screenshots/layer_001_02.png",
            },
            {
                "kind": "layer",
                "target": "gone",
                "target_id": "not-a-layer",
                "page": "Symbology",
                "image": "images/screenshots/layer_999_01.png",
            },
        ],
    }
    md = render_markdown(m)
    import re

    def heading(title):
        return re.search(rf"^#+ [\d.]+ {re.escape(title)}$", md, re.M).start()

    appendix = heading("Appendix: QGIS dialog screenshots")
    # Woven into the chapters, before the appendix, next to the settings they show.
    general = md.index("![Screenshot: Project Properties > General](images/screenshots/project_01.png)")
    assert heading("Project settings") < general < appendix
    rendering = md.index("](images/screenshots/layer_001_02.png)")
    assert heading("Rendering") > heading("Other layer settings") and heading("Rendering") < rendering < appendix
    assert "2 fields showing paths or logins are blacked out" in md
    assert "| Project Properties | Data Sources | it lists data sources | 1 |" in md
    # A screenshot no chapter claims still appears, in the appendix.
    assert md.index("](images/screenshots/layer_999_01.png)") > heading("Other screenshots") > appendix
    assert lint_markdown(md) == []


def test_counts_agree_in_number():
    assert fmt_count(1, "page") == "1 page"
    assert fmt_count(0, "page") == "0 pages"
    assert fmt_count(1200, "item") == "1,200 items"
    assert fmt_count(1, "table or frame", "tables or frames") == "1 table or frame"
    assert fmt_count(2, "table or frame", "tables or frames") == "2 tables or frames"

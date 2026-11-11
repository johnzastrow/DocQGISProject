"""Renderers on a hand-built model: escaping, readability lint, strict JSON."""

import json

import pytest

from core.model import CrsDoc, DocModel, FieldDoc, LayerDoc, Problem, ProjectDoc, SourceDoc, TreeNode, VariableDoc
from core.options import DocOptions
from render.json_out import render_json
from render.md_out import render_markdown
from render.text import md_code, md_text

from ..readability import lint_markdown

HOSTILE = "<script>alert(1)</script> | *b* [l](http://x) `c` _u_ &lt;"


def _model():
    m = DocModel()
    m.generator = {"plugin_version": "0.1.0-dev", "qgis_version": "4.2", "generated_at": "2026-11-11T00:00:00+00:00"}
    m.options = DocOptions().to_dict()
    m.project = ProjectDoc(title=HOSTILE, file_name="p.qgz", path_storage="Relative", crs=CrsDoc("EPSG:4326", "WGS 84", True))
    lyr = LayerDoc(
        id="l1",
        name=HOSTILE,
        layer_type="Vector",
        valid=True,
        data_loaded=True,
        source=SourceDoc(provider="ogr", uri="./d.gpkg|layername=t", parts={"path": "/x/d.gpkg", "layerName": "t"},
                         path="/x/d.gpkg", path_relative="./d.gpkg"),
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
    assert set(data) == {"schema", "generator", "options", "semantic", "problems", "redactions"}
    lyr = data["semantic"]["layers"][0]
    assert lyr["extent"][3] is None  # NaN became null
    assert data["semantic"]["variables"][0]["value"] == {"redacted": "api_key"}


@pytest.mark.parametrize(
    "kwargs",
    [{"formats": ("json", "docx")}, {"formats": ()}, {"detail": "everything"}, {"redact": "yes"}, {"formats": ("pdf",)}],
)
def test_options_reject_invalid(kwargs):
    with pytest.raises(ValueError):
        DocOptions(**kwargs).validate()

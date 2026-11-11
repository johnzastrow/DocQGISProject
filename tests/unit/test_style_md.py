"""Styling chapter formatting: colours, units, diffs, label settings, no raw reprs."""

from core.model import LayerDoc
from render.md_out import _Doc
from render.style_md import fmt_color, fmt_value, humanize, style_chapter, symbol_diff

from ..readability import lint_markdown


def _sym(color, width="0.3"):
    return {
        "type": "Fill",
        "opacity": 1.0,
        "layers": [
            {
                "class": "SimpleFill",
                "name": "Simple Fill",
                "enabled": True,
                "properties": {"color": color, "outline_width": width, "outline_width_unit": "MM"},
                "non_default": ["color", "outline_width"],
                "data_defined": [{"name": "fillColor", "expression": "\"zone\" = 'A'", "field": None, "value": None}],
                "effect": None,
                "sub_symbol": None,
            }
        ],
    }


def test_humanize_and_colors():
    assert humanize("outline_width") == "Outline width"
    assert humanize("fontSizeUnit") == "Font size unit"
    assert fmt_color("224,192,104,255,rgb:0.87,0.75,0.4,1") == "`#e0c068`"
    assert fmt_color("0,0,0,128") == "`#000000` at 50 % opacity"
    assert fmt_color("1,2") is None and fmt_color("300,0,0,255") is None


def test_fmt_value_never_emits_repr():
    assert "{" not in fmt_value({"a_b": 1, "c": {"d": 2}})
    assert fmt_value("<symbol name='x'/>").startswith("Embedded symbol")
    assert fmt_value(True) == "Yes"
    assert fmt_value("x" * 500).endswith("...`")


def test_symbol_diff():
    assert symbol_diff(_sym("1,2,3,255"), _sym("1,2,3,255")) == "Same as first"
    assert "Fill colour `#0a0b0c`" in symbol_diff(_sym("1,2,3,255"), _sym("10,11,12,255"))


def test_style_chapter_categorized_and_labels_pass_lint():
    lyr = LayerDoc(id="l", name="zones", layer_type="Vector")
    lyr.style = {
        "renderer": {
            "type": "categorizedSymbol",
            "name": "Categorized",
            "attribute": "zone",
            "properties": {},
            "categories": [
                {
                    "value": "A",
                    "label": "Zone <A>",
                    "render": True,
                    "symbol": _sym("1,2,3,255"),
                    "image": "images/x/a.png",
                },
                {"value": "", "label": "", "render": False, "symbol": _sym("9,9,9,255"), "image": None},
            ],
        },
        "labeling": {
            "enabled": True,
            "type": "simple",
            "settings": {
                "field": "name",
                "is_expression": False,
                "settings": {"text-style.fontSize": "9", "text-style.text-buffer.bufferDraw": "1"},
                "non_default": ["text-style.fontSize", "text-style.text-buffer.bufferDraw"],
                "data_defined": [],
            },
        },
        "legend": [],
        "qml": "styles/001_zones.qml",
        "named_styles": {"current": "default", "all": ["default"]},
    }
    doc = _Doc()
    style_chapter(doc, lyr)
    text = doc.text()
    assert lint_markdown(text) == []
    assert "![Symbol for Zone &lt;A>](images/x/a.png)" in text
    assert "All other values" in text
    assert "| Buffer draw | Yes | Layer Properties > Labels > Buffer |" in text
    assert "0.3 mm" in text and "(data-defined)" in text
    assert "`styles/001_zones.qml`" in text

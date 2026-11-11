"""P2 acceptance: every renderer and symbol-layer type in the fixtures is documented with all
properties; QML saved; legend and symbol images saved; labels and raster renderers covered."""

import json
import sys
from pathlib import Path
from xml.dom import minidom

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readability import lint_markdown  # noqa: E402


@pytest.fixture(scope="module")
def styling(plugin_pkg, fixtures_dir, tmp_path_factory):
    from DocQGISProject.core.runner import document_project

    out = tmp_path_factory.mktemp("styling_out")
    result = document_project(str(fixtures_dir / "styling.qgz"), str(out))
    data = json.loads((out / "project.json").read_text(encoding="utf-8"))
    md = (out / "report.md").read_text(encoding="utf-8")
    layers = {lyr["name"]: lyr for lyr in data["semantic"]["layers"]}
    return result, data, md, layers, out


def test_no_errors_and_readable(styling):
    _result, data, md, _layers, out = styling
    assert not [p for p in data["problems"] if p["severity"] == "error"], data["problems"]
    assert lint_markdown(md) == []
    # every image the report links to exists
    for rel in __import__("re").findall(r"\]\((images/[^)]+)\)", md):
        assert (out / rel).is_file(), rel


def test_every_renderer_documented(styling):
    layers = styling[3]
    expected = {
        "single": "singleSymbol",
        "categorized": "categorizedSymbol",
        "graduated": "graduatedSymbol",
        "rule-based": "RuleRenderer",
        "inverted polygon": "invertedPolygonRenderer",
        "2.5D": "25dRenderer",
        "point cluster": "pointCluster",
        "point displacement": "pointDisplacement",
        "heatmap": "heatmapRenderer",
        "null symbol": "nullSymbol",
        "dem pseudocolor": "singlebandpseudocolor",
        "dem hillshade": "hillshade",
        "dem gray": "singlebandgray",
        "landcover paletted": "paletted",
    }
    for name, rtype in expected.items():
        assert layers[name]["style"]["renderer"]["type"] == rtype, name
    cat = layers["categorized"]["style"]["renderer"]
    assert [c["value"] for c in cat["categories"]] == ["A", "B", "C"]
    assert all(c["image"] and c["symbol"]["layers"] for c in cat["categories"])
    grad = layers["graduated"]["style"]["renderer"]
    assert [(r["lower"], r["upper"]) for r in grad["ranges"]] == [(100, 130), (130, 160), (160, 190)]
    rules = layers["rule-based"]["style"]["renderer"]["rules"]
    assert [r["else"] for r in rules] == [False, False, True] and rules[0]["filter"] == "\"zone\" = 'A'"
    cluster = layers["point cluster"]["style"]["renderer"]
    assert cluster["embedded"]["type"] == "singleSymbol" and cluster["cluster_symbol"]["layers"]
    assert layers["inverted polygon"]["style"]["renderer"]["embedded"]["type"] == "singleSymbol"
    assert layers["heatmap"]["style"]["renderer"]["properties"]["radius"] == "10"
    assert layers["2.5D"]["style"]["renderer"]["symbols"]


def test_every_symbol_layer_type_documented_with_all_properties(styling):
    from qgis.core import Qgis, QgsApplication

    layers = styling[3]
    reg = QgsApplication.symbolLayerRegistry()
    for zoo, stype in (
        ("zoo markers", Qgis.SymbolType.Marker),
        ("zoo lines", Qgis.SymbolType.Line),
        ("zoo fills", Qgis.SymbolType.Fill),
    ):
        sym = layers[zoo]["style"]["renderer"]["symbol"]
        classes = [sl["class"] for sl in sym["layers"]]
        assert sorted(classes) == sorted(reg.symbolLayersForType(stype)), zoo
        for sl in sym["layers"]:
            assert sl["properties"], f"{zoo}: {sl['class']} has no properties"
            assert sl["name"]


def test_symbol_details(styling):
    layers = styling[3]
    line = layers["multi-layer line"]["style"]["renderer"]["symbol"]
    assert [sl["class"] for sl in line["layers"]] == ["SimpleLine", "SimpleLine", "MarkerLine"]
    dd = line["layers"][1]["data_defined"]
    assert dd and dd[0]["name"] == "outlineWidth" and "major" in dd[0]["expression"]
    assert line["layers"][2]["sub_symbol"]["type"] == "Marker"
    single = layers["single"]["style"]["renderer"]["symbol"]["layers"][0]
    assert single["effect"]["effects"][0]["type"] == "dropShadow"
    assert "color" in single["non_default"]


def test_labels(styling):
    layers = styling[3]
    simple = layers["categorized"]["style"]["labeling"]
    assert simple["type"] == "simple" and simple["enabled"]
    s = simple["settings"]
    assert s["field"] == "name"
    assert any(k.endswith("bufferDraw") for k in s["non_default"])
    assert any(k.endswith("shadowDraw") for k in s["non_default"])
    rb = layers["multi-layer line"]["style"]["labeling"]
    assert rb["type"] == "rule-based" and rb["rules"][0]["filter"] == "\"class\" = 'major'"


def test_rasters(styling):
    layers = styling[3]
    pseudo = layers["dem pseudocolor"]["style"]["renderer"]
    assert [i["label"] for i in pseudo["items"]] == ["Low", "Mid", "High"]
    assert pseudo["pipe"]["contrast"] == 10 and pseudo["pipe"]["saturation"] == -20
    pal = layers["landcover paletted"]["style"]["renderer"]
    assert [i["color"] for i in pal["items"]] == ["#33a02c", "#ffff99", "#1f78b4"]
    hill = layers["dem hillshade"]["style"]["renderer"]["properties"]
    assert hill["azimuth"] == "315" and hill["angle"] == "45"


def test_qml_and_images(styling):
    from qgis.PyQt.QtGui import QImage

    _r, _d, _md, layers, out = styling
    for name, lyr in layers.items():
        qml = lyr["style"]["qml"]
        assert qml and qml.startswith("styles/"), name
        dom = minidom.parse(str(out / qml))
        assert dom.documentElement.tagName == "qgis"
    legend = layers["categorized"]["style"]["legend"]
    assert len(legend) == 3 and all(e["image"] for e in legend)
    img = QImage(str(out / legend[0]["image"]))
    assert img.width() == round(32 * 120 / 96)  # default image_dpi 120
    assert any(e["key"] == "ramp" and e["image"] for e in layers["heatmap"]["style"]["legend"])


def test_images_off_and_dpi(plugin_pkg, fixtures_dir, tmp_path):
    from qgis.PyQt.QtGui import QImage

    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project

    document_project(str(fixtures_dir / "styling.qgz"), str(tmp_path / "off"), DocOptions(images=False))
    assert not (tmp_path / "off" / "images").exists()
    assert (tmp_path / "off" / "styles").is_dir()
    assert lint_markdown((tmp_path / "off" / "report.md").read_text(encoding="utf-8")) == []

    document_project(str(fixtures_dir / "styling.qgz"), str(tmp_path / "hi"), DocOptions(image_dpi=240))
    img = QImage(str(next((tmp_path / "hi" / "images").rglob("legend_001.png"))))
    assert img.width() == 80


def test_artifact_budget_is_reported(plugin_pkg, fixtures_dir):
    from DocQGISProject.core.artifacts import ArtifactSink
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import collect, open_project

    sink = ArtifactSink(max_files=3)
    model = collect(open_project(fixtures_dir / "styling.qgz"), DocOptions().validate(), None, sink)
    assert len(sink.files) == 3 and sink.dropped > 0
    assert any(p.section == "images" for p in model.problems)


def test_qml_redaction_is_structural(plugin_pkg, fixtures_dir, tmp_path, fake_secrets):
    """Secrets leave the QML, but harmless attributes such as pass="0" stay intact."""
    from qgis.core import QgsMapLayer, QgsProject
    from qgis.PyQt.QtXml import QDomDocument

    from DocQGISProject.core.runner import document_project

    document_project(str(fixtures_dir / "sources.qgz"), str(tmp_path))
    document_project(str(fixtures_dir / "styling.qgz"), str(tmp_path / "s"))
    for qml in list(tmp_path.glob("styles/*.qml")) + list((tmp_path / "s").glob("styles/*.qml")):
        text = qml.read_text(encoding="utf-8")
        assert not any(s in text for s in fake_secrets), qml.name
        assert 'pass="[REDACTED' not in text, qml.name
    # A redacted style still loads back into QGIS.
    project = QgsProject()
    project.read(str(fixtures_dir / "styling.qgz"))
    layer = project.mapLayersByName("categorized")[0]
    doc = QDomDocument()
    ok, _msg = doc.setContent((tmp_path / "s" / "styles" / "017_categorized.qml").read_text(encoding="utf-8"))[:2]
    assert ok
    ok, msg = layer.importNamedStyle(doc, QgsMapLayer.StyleCategory.Symbology)
    assert ok, msg
    assert layer.renderer().type() == "categorizedSymbol"

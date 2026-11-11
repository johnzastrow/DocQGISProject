"""The fixture generator builds projects that reload with valid layers, layouts, themes and relations."""

import importlib.util
from pathlib import Path

import pytest

GEN = Path(__file__).resolve().parents[1] / "fixtures" / "make_fixtures.py"


@pytest.fixture(scope="module")
def fixtures_dir(qgis_app, tmp_path_factory):
    spec = importlib.util.spec_from_file_location("make_fixtures", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path_factory.mktemp("fixtures")
    gpkg = out / "fixture_data.gpkg"
    mod.write_data(gpkg)
    (out / "assets").mkdir()
    svg = out / "assets" / "north.svg"
    svg.write_bytes(mod.REPO_ICON.read_bytes())
    mod.make_basic(out, gpkg)
    mod.make_styling(out, gpkg)
    mod.make_layout(out, gpkg, svg)
    return out


def _read(path):
    from qgis.core import QgsProject

    project = QgsProject()
    assert project.read(str(path)), project.error()
    invalid = [lyr.name() for lyr in project.mapLayers().values() if not lyr.isValid()]
    assert not invalid, f"invalid layers in {path.name}: {invalid}"
    return project


def test_basic(fixtures_dir):
    p = _read(fixtures_dir / "basic.qgz")
    assert len(p.mapLayers()) == 5
    assert p.relationManager().relation("zones_sites").isValid()
    assert set(p.mapThemeCollection().mapThemes()) == {"All", "Zones only"}
    assert p.bookmarkManager().bookmarks()
    groups = {g.name(): g for g in p.layerTreeRoot().findGroups()}
    assert groups["Alternatives (mutually exclusive)"].isMutuallyExclusive()


def test_styling_has_each_renderer(fixtures_dir):
    p = _read(fixtures_dir / "styling.qgz")
    types = {lyr.renderer().type() for lyr in p.mapLayers().values()}
    expected = {
        "singleSymbol", "categorizedSymbol", "graduatedSymbol", "RuleRenderer", "invertedPolygonRenderer",
        "25dRenderer", "pointCluster", "pointDisplacement", "heatmapRenderer", "nullSymbol",
    }
    assert expected <= types, f"missing renderers: {expected - types}"
    trails = p.mapLayersByName("multi-layer line")[0]
    assert trails.labeling().type() == "rule-based"


def test_layout_items(fixtures_dir):
    from qgis.core import QgsLayoutItemRegistry

    p = _read(fixtures_dir / "layout.qgz")
    names = {lay.name() for lay in p.layoutManager().layouts()}
    assert {"Main", "Atlas by zone", "Zone report"} <= names
    main = p.layoutManager().layoutByName("Main")
    types = {item.type() for item in main.items() if hasattr(item, "type")}
    for t in ("LayoutMap", "LayoutLegend", "LayoutScaleBar", "LayoutLabel", "LayoutPicture",
              "LayoutShape", "LayoutPolygon", "LayoutPolyline", "LayoutMarker", "LayoutFrame"):
        assert int(getattr(QgsLayoutItemRegistry, t)) in {int(x) for x in types}, f"{t} missing"
    assert p.layoutManager().layoutByName("Atlas by zone").atlas().enabled()

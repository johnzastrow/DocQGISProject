"""P6: the Processing algorithms wrap the engine and the rebuilder (design section 7)."""

import pytest


@pytest.fixture(scope="module")
def provider(qgis_app, plugin_pkg):
    from qgis.analysis import QgsNativeAlgorithms
    from qgis.core import QgsApplication

    registry = QgsApplication.processingRegistry()
    if registry.providerById("native") is None:
        registry.addProvider(QgsNativeAlgorithms())
    from DocQGISProject.processing_provider.provider import DocQGISProjectProvider

    prov = registry.providerById("docqgisproject")
    if prov is None:
        prov = DocQGISProjectProvider()
        registry.addProvider(prov)
    yield prov
    registry.removeProvider(prov)


def _run(alg_id, params):
    from qgis.core import QgsApplication, QgsProcessingContext, QgsProcessingFeedback, QgsProject

    alg = QgsApplication.processingRegistry().createAlgorithmById(alg_id)
    assert alg is not None, alg_id
    context = QgsProcessingContext()
    context.setProject(QgsProject.instance())
    feedback = QgsProcessingFeedback()
    ok, msg = alg.checkParameterValues(params, context)
    assert ok, msg
    results, ok = alg.run(params, context, feedback)
    return results, ok, feedback


def test_algorithms_registered(provider):
    from qgis.core import Qgis

    ids = sorted(a.id() for a in provider.algorithms())
    assert ids == ["docqgisproject:documentproject", "docqgisproject:rebuildproject"]
    for a in provider.algorithms():
        assert a.shortHelpString()
        assert a.flags() & Qgis.ProcessingAlgorithmFlag.NoThreading  # reads the live project


def test_document_then_rebuild(provider, fixtures_dir, tmp_path):
    out = tmp_path / "doc"
    results, ok, _fb = _run(
        "docqgisproject:documentproject",
        {"INPUT": str(fixtures_dir / "layout.qgz"), "OUTPUT_FOLDER": str(out), "FORMATS": [0, 1], "IMAGES": False},
    )
    assert ok
    assert results["JSON"].endswith("project.json") and results["MARKDOWN"].endswith("report.md")
    assert results["HTML"] is None and results["PDF"] is None
    assert results["FILES"] >= 2 and results["REDACTIONS"] == 0

    target = fixtures_dir / "rebuilt_by_processing.qgz"
    results, ok, _fb = _run(
        "docqgisproject:rebuildproject", {"INPUT": results["JSON"], "OUTPUT": str(target)}
    )
    assert ok and results["OUTPUT"] == str(target) and target.is_file()
    assert results["NEEDS_CREDENTIALS"] == ""


def test_rebuild_with_maps(provider, fixtures_dir, tmp_path):
    out = tmp_path / "doc"
    results, ok, _fb = _run(
        "docqgisproject:documentproject",
        {"INPUT": str(fixtures_dir / "sources.qgz"), "OUTPUT_FOLDER": str(out), "FORMATS": [0], "IMAGES": False},
    )
    assert ok and results["REDACTIONS"] > 0
    import json

    sources = json.loads(open(results["JSON"], encoding="utf-8").read())["rebuild"]["sources"]
    db = next(s["id"] for s in sources if s["kind"] == "database")
    target = fixtures_dir / "rebuilt_sources_by_processing.qgz"
    results, ok, fb = _run(
        "docqgisproject:rebuildproject",
        {"INPUT": results["JSON"], "OUTPUT": str(target), "AUTH_MAP": f"{db}=abc1234", "SOURCE_MAP": ""},
    )
    assert ok and db not in results["NEEDS_CREDENTIALS"].split(",")
    assert results["NEEDS_CREDENTIALS"]  # the web layer


def test_errors_become_processing_errors(provider, fixtures_dir, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema": "docqgisproject/1", "rebuild": null}', encoding="utf-8")
    _results, ok, _fb = _run(
        "docqgisproject:rebuildproject", {"INPUT": str(bad), "OUTPUT": str(tmp_path / "x.qgz")}
    )
    assert not ok
    assert not (tmp_path / "x.qgz").exists()
    _results, ok, _fb = _run(
        "docqgisproject:rebuildproject",
        {"INPUT": str(bad), "OUTPUT": str(tmp_path / "y.qgz"), "AUTH_MAP": "no-equals-sign"},
    )
    assert not ok

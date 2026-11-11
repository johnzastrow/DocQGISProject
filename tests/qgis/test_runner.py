"""P1 acceptance: document_project() writes JSON and Markdown with project, tree, layers,
sources (redacted), fields, relations, variables and themes; nothing secret leaks."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readability import lint_markdown  # noqa: E402


@pytest.fixture(scope="module")
def run(plugin_pkg, fixtures_dir, tmp_path_factory):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project

    def _run(name, **opts):
        out = tmp_path_factory.mktemp(name)
        result = document_project(str(fixtures_dir / f"{name}.qgz"), str(out), DocOptions(**opts))
        data = json.loads((out / "project.json").read_text(encoding="utf-8"))
        md = (out / "report.md").read_text(encoding="utf-8")
        return result, data, md, out

    return _run


def test_basic_project(run):
    result, data, md, out = run("basic")
    sem = data["semantic"]
    assert data["schema"] == "docqgisproject/1"
    assert sem["project"]["title"] == "Basic fixture"  # QGIS 4: title is the metadata title
    assert sem["project"]["crs"]["authid"] == "EPSG:32619"
    assert sem["project"]["path_storage"] == "Relative"
    # tree: groups in order, mutually exclusive group, layers inside
    groups = [c for c in sem["layer_tree"]["children"] if c["kind"] == "group"]
    assert [g["name"] for g in groups] == ["Base", "Features", "Alternatives (mutually exclusive)"]
    assert groups[2]["mutually_exclusive"] is True
    # layers in tree order with fields and data
    names = [lyr["name"] for lyr in sem["layers"]]
    assert names[:3] == ["zones", "sites", "trails"]
    zones = sem["layers"][0]
    assert zones["valid"] and zones["feature_count"] == 9
    assert zones["source"]["path_relative"] == "./fixture_data.gpkg"
    assert [f["name"] for f in zones["fields"]] == ["fid", "id", "name", "zone", "area_ha", "area_km2"]
    virtual = zones["fields"][5]
    assert virtual["origin"] == "Expression" and virtual["expression"] == '"area_ha" / 100'
    assert zones["fields"][2]["alias"] == "Zone name"
    join = sem["layers"][1]["joins"][0]
    assert (join["join_layer_name"], join["join_field"], join["target_field"], join["prefix"]) == (
        "zones",
        "id",
        "zone_id",
        "zone_",
    )
    assert join["fields_subset"] == ["name"] and join["cached"]
    # relations, variables, themes, bookmarks
    rel = sem["relations"][0]
    assert rel["referenced_layer_name"] == "zones" and rel["referencing_layer_name"] == "sites"
    assert rel["field_pairs"] == [{"referencing": "zone_id", "referenced": "id"}]
    assert {v["name"]: v["value"] for v in sem["variables"]} == {
        "fixture_author": "DocQGISProject tests",
        "fixture_revision": "1",
    }
    themes = {t["name"]: [tl["layer_name"] for tl in t["layers"]] for t in sem["themes"]}
    assert "trails" not in themes["Zones only"] and "trails" in themes["All"]
    assert sem["bookmarks"][0]["name"] == "Centre cell"
    assert not [p for p in data["problems"] if p["severity"] == "error"]
    # markdown is readable and complete
    assert lint_markdown(md) == []
    for heading in ("## 2. How to recreate this project", "## 6. Relations", "## 8. Map themes"):
        assert heading in md
    assert "Sites in zone" in md and "Zones only" in md
    assert set(os.listdir(out)) == {"project.json", "report.md", ".docqgisproject-manifest.json", "images", "styles"}


def test_sources_redacted_and_remote_not_contacted(run, fake_secrets):
    result, data, md, out = run("sources")
    assert len(fake_secrets) == 6
    files = [p for p in out.rglob("*") if p.is_file()]
    assert any(p.suffix == ".qml" for p in files)
    for path in files:
        text = path.read_bytes().decode("utf-8", errors="replace")
        for secret in fake_secrets:
            assert secret not in text, f"{secret} leaked into {path.name}"
    by_name = {lyr["name"]: lyr for lyr in data["semantic"]["layers"]}
    pg = by_name["postgis sites"]
    assert pg["source"]["remote"] and not pg["data_loaded"]
    assert pg["source"]["parts"]["password"] == {"redacted": "password"}
    assert pg["source"]["parts"]["key"] == "id"  # primary-key column survives
    assert by_name["tiles with key"]["source"]["remote"]
    assert data["redactions"] == {"user": 1, "password": 1, "userinfo": 1, "api_key": 1, "token": 1}  # each secret once
    severities = {(p["severity"], p["layer_id"] is not None) for p in data["problems"]}
    assert ("warning", True) in severities  # the missing file
    # the hostile layer name is inert in Markdown
    assert "<script" not in md
    assert lint_markdown(md) == []


def test_styling_and_layout_projects_document_cleanly(run):
    for name in ("styling", "layout"):
        _result, data, md, _out = run(name)
        assert not [p for p in data["problems"] if p["severity"] == "error"], data["problems"]
        assert all(lyr["valid"] for lyr in data["semantic"]["layers"])
        assert lint_markdown(md) == []


def test_load_data_off_reads_nothing(run):
    _result, data, _md, _out = run("basic", load_data=False)
    assert all(not lyr["data_loaded"] and lyr["feature_count"] is None for lyr in data["semantic"]["layers"])


def test_redaction_off_is_flagged(run, fixtures_dir):
    _result, data, md, _out = run("sources", redact=False)
    assert "redaction was turned off" in md
    assert any(p["section"] == "security" for p in data["problems"])


def test_refuses_foreign_files_and_bad_input(plugin_pkg, fixtures_dir, tmp_path):
    from DocQGISProject.core.runner import document_project
    from DocQGISProject.core.safe_paths import OutputExistsError

    (tmp_path / "report.md").write_text("mine")
    with pytest.raises(OutputExistsError):
        document_project(str(fixtures_dir / "basic.qgz"), str(tmp_path))
    assert (tmp_path / "report.md").read_text() == "mine"
    assert not (tmp_path / "project.json").exists()
    with pytest.raises(ValueError):
        document_project(str(fixtures_dir / "fixture_data.gpkg"), str(tmp_path / "o"))
    with pytest.raises(FileNotFoundError):
        document_project(str(fixtures_dir / "nope.qgz"), str(tmp_path / "o"))


def test_cancel_writes_nothing(plugin_pkg, fixtures_dir, tmp_path):
    from qgis.core import QgsFeedback

    from DocQGISProject.core.runner import Cancelled, document_project

    fb = QgsFeedback()
    fb.cancel()
    with pytest.raises(Cancelled):
        document_project(str(fixtures_dir / "basic.qgz"), str(tmp_path), feedback=fb)
    assert not (tmp_path / "report.md").exists()


def test_live_project_object_is_accepted_and_untouched(plugin_pkg, fixtures_dir, tmp_path):
    from qgis.core import QgsProject

    from DocQGISProject.core.runner import document_project

    project = QgsProject()
    assert project.read(str(fixtures_dir / "basic.qgz"))
    before = project.isDirty()
    result = document_project(project, str(tmp_path))
    assert len(result.model.layers) == 5
    assert project.isDirty() == before

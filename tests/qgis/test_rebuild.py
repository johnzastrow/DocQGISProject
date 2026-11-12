"""P5 acceptance: the JSON validates against the schema; the rebuilder recreates every fixture
project; the round trip (project A -> JSON -> project B) keeps the XML and the rendered layout
pages; credentials and code never come through; hostile JSON is refused (design R9, section 9)."""

import copy
import json
from pathlib import Path

import pytest

FIXTURES = ("basic", "styling", "layout", "sources")
SCHEMA = Path(__file__).resolve().parents[2] / "docs" / "schema" / "docqgisproject-1.schema.json"


@pytest.fixture(scope="module")
def documented(plugin_pkg, fixtures_dir, tmp_path_factory):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project

    out = {}
    for name in FIXTURES:
        folder = tmp_path_factory.mktemp(f"rb_{name}")
        document_project(str(fixtures_dir / f"{name}.qgz"), str(folder), DocOptions(formats=["json"], images=False))
        out[name] = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    return out


_counter = iter(range(10**6))


def _target(fixtures_dir, name):
    """A fresh output path beside the fixtures (relative data paths stay valid)."""
    return fixtures_dir / f"rebuilt_{name}_{next(_counter)}.qgz"


def _xml(path):
    from qgis.PyQt.QtXml import QDomDocument

    from DocQGISProject.core.collectors.tier_b import read_project_xml

    doc = QDomDocument()
    doc.setContent(read_project_xml(str(path)))
    return doc.toString(1)


# --------------------------------------------------------------------------- payload


@pytest.mark.parametrize("name", FIXTURES)
def test_json_validates_against_schema(documented, name):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(documented[name])


def test_payload_parameterises_every_source(documented):
    for name, doc in documented.items():
        rb = doc["rebuild"]
        xml = rb["project_xml"]
        assert "<datasource>./" not in xml, name
        for src in rb["sources"]:
            assert f"@docqgisproject:source/{src['id']}" in xml
    files = [s["file"] for s in documented["basic"]["rebuild"]["sources"]]
    assert all(f["exists"] and len(f["sha256"]) == 64 for f in files)


def test_payload_embeds_layout_picture(documented):
    res = documented["layout"]["rebuild"]["resources"]
    assert [(r["name"], r["ref"]) for r in res] == [("north.svg", "./assets/north.svg")]


def test_no_false_redactions_in_clean_projects(documented):
    # Regression: serialised XML inside attribute values (a label's lineSymbol) holds
    # pass="0", which the text redactor used to read as a password.
    for name in ("basic", "styling", "layout"):
        assert documented[name]["redactions"] == {}, name


def test_payload_never_holds_secrets(documented, fake_secrets):
    text = json.dumps(documented["sources"]["rebuild"])
    for secret in fake_secrets:
        assert secret not in text


# --------------------------------------------------------------------------- round trip


@pytest.mark.parametrize("name", ("basic", "styling", "layout"))
def test_round_trip_xml(documented, fixtures_dir, name):
    from DocQGISProject.core.rebuild import rebuild_project

    target = _target(fixtures_dir, name)
    result = rebuild_project(copy.deepcopy(documented[name]), target)
    assert result.problems == []
    a = _xml(fixtures_dir / f"{name}.qgz").splitlines()
    b = _xml(target).splitlines()
    assert len(a) == len(b)
    files_dir = f"./{target.stem}_files/"
    for la, lb in zip(a, b):
        if la != lb:
            # Allow-list: embedded files are repointed at the rebuilt project's own folder, and
            # (paths="relative", the default) absolute paths QGIS stored itself, such as an atlas
            # coverageLayerSource, are written relative to the project folder.
            expected = la.replace("./assets/", files_dir).replace(str(fixtures_dir) + "/", "./")
            assert expected == lb, (la[:200], lb[:200])
    if name == "layout":
        assert (fixtures_dir / f"{target.stem}_files" / "north.svg").is_file()


def _page_bytes(path):
    from qgis.core import QgsLayoutExporter, QgsProject

    from DocQGISProject.core.collectors.layouts import render_hazard

    project = QgsProject()
    assert project.read(str(path))
    pages = []
    for layout in project.layoutManager().printLayouts():
        # Same guard as the plugin: QGIS 4.2.3 segfaults drawing a chart item whose source
        # layer is not loaded. Such layouts are compared by XML only.
        if any(render_hazard(item) for item in layout.items()):
            pages.append((layout.name(), "skipped", 0, b""))
            continue
        exporter = QgsLayoutExporter(layout)
        for page in range(layout.pageCollection().pageCount()):
            img = exporter.renderPageToImage(page, dpi=30)
            ptr = img.constBits()
            ptr.setsize(img.sizeInBytes())
            pages.append((layout.name(), img.width(), img.height(), bytes(ptr)))
    project.clear()
    return pages


def test_round_trip_renders_the_same_layout_pages(documented, fixtures_dir):
    from DocQGISProject.core.rebuild import rebuild_project

    target = _target(fixtures_dir, "layout")
    rebuild_project(copy.deepcopy(documented["layout"]), target)
    a, b = _page_bytes(fixtures_dir / "layout.qgz"), _page_bytes(target)
    assert a and len(a) == len(b)
    assert any(w != "skipped" for _n, w, _h, _d in a), "no layout page could be rendered"
    for (na, wa, ha, da), (nb, wb, hb, db) in zip(a, b):
        assert (na, wa, ha) == (nb, wb, hb)
        if wa == "skipped":
            continue
        differing = sum(1 for x, y in zip(da, db) if abs(x - y) > 8)
        assert differing / len(da) < 0.002, f"{na}: {differing} of {len(da)} bytes differ"


def test_sources_rebuild_without_credentials(documented, fixtures_dir, fake_secrets):
    from DocQGISProject.core.rebuild import rebuild_project

    rb = documented["sources"]["rebuild"]
    db = next(s["id"] for s in rb["sources"] if s["kind"] == "database")
    target = _target(fixtures_dir, "sources")
    result = rebuild_project(copy.deepcopy(documented["sources"]), target, auth_map={db: "abc1234"})
    xml = _xml(target)
    for secret in fake_secrets:
        assert secret not in xml
    assert "REDACTED" not in "".join(line for line in xml.splitlines() if "<datasource>" in line)
    assert "authcfg=abc1234" in xml
    assert db not in result.needs_credentials
    assert result.needs_credentials  # the web layer had its key removed and no auth given


# --------------------------------------------------------------------------- safety


def test_never_overwrites(documented, fixtures_dir):
    from DocQGISProject.core.rebuild import RebuildError, rebuild_project

    target = _target(fixtures_dir, "layout")
    rebuild_project(copy.deepcopy(documented["layout"]), target)
    before = target.read_bytes()
    with pytest.raises(RebuildError, match="never overwrites"):
        rebuild_project(copy.deepcopy(documented["layout"]), target)
    assert target.read_bytes() == before
    other = _target(fixtures_dir, "layout")
    (fixtures_dir / f"{other.stem}_files").mkdir()
    with pytest.raises(RebuildError, match="never overwrites"):
        rebuild_project(copy.deepcopy(documented["layout"]), other)
    assert not other.exists()


def _with_absolute_source(doc):
    doc = copy.deepcopy(doc)
    rb = doc["rebuild"]
    src = rb["sources"][0]
    src["uri"] = src["uri"].replace("./fixture_data.gpkg", "/old/place/fixture_data.gpkg")
    src["file"]["path"] = "/old/place/fixture_data.gpkg"
    return doc


def test_unmapped_absolute_path_refused_and_mapping_works(documented, fixtures_dir):
    from DocQGISProject.core.rebuild import RebuildError, rebuild_project

    doc = _with_absolute_source(documented["basic"])
    target = _target(fixtures_dir, "basic")
    with pytest.raises(RebuildError, match="absolute path"):
        rebuild_project(doc, target)
    assert not target.exists()
    rebuild_project(doc, target, source_map={"/old/place": str(fixtures_dir)})
    assert f"{fixtures_dir}/fixture_data.gpkg|layername=" in _xml(target)


def test_code_is_stripped(documented, fixtures_dir):
    from DocQGISProject.core.rebuild import rebuild_project

    doc = copy.deepcopy(documented["basic"])
    xml = doc["rebuild"]["project_xml"]
    macros = (
        '<properties name="Macros"><properties name="pythonCode" type="QString">'
        'import os; os.system("touch /tmp/pwned")</properties></properties>'
        '<properties name="ExpressionFunctions"><properties name="pythonCode" type="QString">'
        "import os</properties></properties>"
    )
    xml = xml.replace('<properties name="properties">', '<properties name="properties">' + macros, 1)
    xml = xml.replace(
        "<editforminitcodesource>0</editforminitcodesource>",
        "<editforminitcodesource>2</editforminitcodesource><editforminitcode>import os</editforminitcode>",
        1,
    )
    action = (
        '<actionsetting type="1" name="evil" action="import os" icon="" shortTitle="" capture="0" '
        'notificationMessage="" isEnabledOnlyWhenEditable="0" id="{00000000-0000-0000-0000-000000000001}"/>'
    )
    xml = xml.replace("<attributeactions/>", f"<attributeactions>{action}</attributeactions>", 1)
    assert "pythonCode" in xml and "actionsetting" in xml
    doc["rebuild"]["project_xml"] = xml
    target = _target(fixtures_dir, "basic")
    result = rebuild_project(doc, target)
    out = _xml(target)
    assert "pythonCode" not in out and "touch /tmp/pwned" not in out
    assert 'name="evil"' not in out and "import os" not in out
    msg = next(m for _sev, m in result.problems if "could run code" in m)
    for part in ("project macros", "project expression functions", "form-init", "layer actions"):
        assert part in msg


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda rb: rb.update(project_xml=rb["project_xml"].replace("@docqgisproject:source/s1", "@docqgisproject:source/s99")), "undeclared"),
        (lambda rb: rb["resources"].append(dict(rb["resources"][0], name="../../escape.svg")), "plain file name"),
        (lambda rb: rb.update(project_xml='<!DOCTYPE qgis [<!ENTITY x SYSTEM "file:///etc/passwd">]><qgis>&x;</qgis>'), "DOCTYPE"),
        (lambda rb: rb["resources"][0].update(sha256="0" * 64), "does not match"),
    ],
)
def test_hostile_json_refused_without_output(documented, fixtures_dir, mutate, match):
    from DocQGISProject.core.rebuild import RebuildError, rebuild_project

    doc = copy.deepcopy(documented["layout"])
    mutate(doc["rebuild"])
    target = _target(fixtures_dir, "layout")
    with pytest.raises(RebuildError, match=match):
        rebuild_project(doc, target)
    assert not target.exists()
    assert not (fixtures_dir / f"{target.stem}_files").exists()


def test_rebuild_from_file_path(documented, fixtures_dir, tmp_path):
    from DocQGISProject.core.rebuild import rebuild_project

    path = tmp_path / "project.json"
    path.write_text(json.dumps(documented["basic"]), encoding="utf-8")
    target = _target(fixtures_dir, "basic")
    result = rebuild_project(str(path), str(target))
    assert target.is_file() and result.files == [str(target)]

"""The rebuilder's input validation (core/schema.py) against a corpus of hostile JSON,
the URI helpers (core/uri_text.py), and the published JSON Schema."""

import base64
import copy
import hashlib
import json

import pytest

from core.model import DocModel
from core.schema import (
    MAX_RESOURCE_BYTES,
    SchemaError,
    load_json_bytes,
    validate_rebuild_document,
)
from core.uri_text import is_absolute, map_path, parse_map_arg, strip_redacted
from render.json_out import model_to_json_dict

from ._repo import ROOT

QGIS_HEAD = "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'/>"


def _resource(name="north.svg", data=SVG, ref="./assets/north.svg"):
    return {
        "name": name,
        "ref": ref,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


def good_doc():
    xml = (
        QGIS_HEAD + '<qgis version="4.2.3"><projectlayers><maplayer><id>l1</id>'
        "<datasource>@docqgisproject:source/s1</datasource><provider>ogr</provider></maplayer>"
        "</projectlayers></qgis>"
    )
    return {
        "schema": "docqgisproject/1",
        "rebuild": {
            "format": "qgis-project-xml/1",
            "project_file": "My project (v2).qgz",
            "qgis_version": "4.2.3",
            "project_xml": xml,
            "sources": [
                {
                    "id": "s1",
                    "provider": "ogr",
                    "kind": "file",
                    "uri": "./data.gpkg|layername=a",
                    "layer_ids": ["l1"],
                    "redacted": False,
                    "file": {"path": "./data.gpkg", "exists": True, "size": 10, "sha256": "0" * 64},
                }
            ],
            "resources": [_resource()],
            "notes": [],
        },
    }


def test_good_document_passes():
    rb, files = validate_rebuild_document(good_doc())
    assert files == {"north.svg": SVG}
    assert rb["sources"][0]["id"] == "s1"


def _mut(fn):
    doc = copy.deepcopy(good_doc())
    fn(doc)
    return doc


def _set(path, value):
    def fn(doc):
        obj = doc
        for key in path[:-1]:
            obj = obj[key]
        obj[path[-1]] = value

    return fn


RB = "rebuild"
HOSTILE = {
    "wrong schema id": _set(["schema"], "docqgisproject/2"),
    "no rebuild part": lambda d: d.pop(RB),
    "rebuild is null": _set([RB], None),
    "unknown format": _set([RB, "format"], "qgis-project-xml/9"),
    "extra key in rebuild": _set([RB, "run_this"], "import os"),
    "project_file with a path": _set([RB, "project_file"], "../../etc/passwd"),
    "project_file with backslash": _set([RB, "project_file"], "..\\evil.qgz"),
    "xml with internal entity (billion laughs)": lambda d: d[RB].update(
        project_xml='<!DOCTYPE qgis [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><qgis>&b;</qgis>'
    ),
    "xml with external entity (XXE)": lambda d: d[RB].update(
        project_xml='<!DOCTYPE qgis [<!ENTITY x SYSTEM "file:///etc/passwd">]><qgis>&x;</qgis>'
    ),
    "QGIS doctype plus an entity": lambda d: d[RB].update(
        project_xml=QGIS_HEAD + '<!ENTITY x SYSTEM "file:///etc/passwd"><qgis>&x;</qgis>'
    ),
    "not a qgis document": _set([RB, "project_xml"], "<html><script>alert(1)</script></html>"),
    "nul in xml": _set([RB, "project_xml"], "<qgis>\x00</qgis>"),
    "token for an undeclared source": lambda d: d[RB].update(
        project_xml="<qgis><datasource>@docqgisproject:source/s9</datasource></qgis>"
    ),
    "duplicate source id": lambda d: d[RB]["sources"].append(copy.deepcopy(d[RB]["sources"][0])),
    "bad source id": _set([RB, "sources", 0, "id"], "s1; rm -rf /"),
    "provider with shell": _set([RB, "sources", 0, "provider"], "ogr;whoami"),
    "unknown source kind": _set([RB, "sources", 0, "kind"], "exec"),
    "source without layers": _set([RB, "sources", 0, "layer_ids"], []),
    "layer id with markup": _set([RB, "sources", 0, "layer_ids"], ["<script>"]),
    "uri too long": _set([RB, "sources", 0, "uri"], "a" * 70000),
    "uri with nul": _set([RB, "sources", 0, "uri"], "./a.gpkg\x00.txt"),
    "bad hash in file info": _set([RB, "sources", 0, "file", "sha256"], "XYZ"),
    "negative size": _set([RB, "sources", 0, "file", "size"], -1),
    "boolean where a size is wanted": _set([RB, "sources", 0, "file", "size"], True),
    "extra key in file info": _set([RB, "sources", 0, "file", "exec"], "x"),
    "resource name traversal": _set([RB, "resources", 0, "name"], "../../.bashrc.svg"),
    "resource name absolute": _set([RB, "resources", 0, "name"], "/etc/x.svg"),
    "resource hidden file": _set([RB, "resources", 0, "name"], ".evil.svg"),
    "resource executable extension": lambda d: d[RB].update(resources=[_resource(name="run.py")]),
    "resource html extension": lambda d: d[RB].update(resources=[_resource(name="page.html")]),
    "resource hash mismatch": _set([RB, "resources", 0, "sha256"], "0" * 64),
    "resource size mismatch": _set([RB, "resources", 0, "size"], 3),
    "resource not base64": _set([RB, "resources", 0, "data_base64"], "!!!not base64!!!"),
    "resource oversize declared": _set([RB, "resources", 0, "size"], MAX_RESOURCE_BYTES + 1),
    "duplicate resource name (case)": lambda d: d[RB]["resources"].append(_resource(name="NORTH.svg")),
    "empty ref": _set([RB, "resources", 0, "ref"], ""),
    "too many notes": _set([RB, "notes"], ["x"] * 101),
}


@pytest.mark.parametrize("case", sorted(HOSTILE))
def test_hostile_documents_rejected(case):
    with pytest.raises(SchemaError):
        validate_rebuild_document(_mut(HOSTILE[case]))


def test_resources_total_cap():
    big = b"x" * (9 * 1024 * 1024)
    doc = _mut(lambda d: d[RB].update(resources=[_resource(f"r{i}.png", big) for i in range(3)]))
    with pytest.raises(SchemaError, match="exceed"):
        validate_rebuild_document(doc)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a": 1, "a": 2}',  # duplicate keys: parsers disagree which wins
        b'{"a": NaN}',
        b'{"a": Infinity}',
        b"[1, 2, 3]",  # top level must be an object
        b"\xff\xfe{}",  # not UTF-8
        b'{"a": ' * 100 + b"1" + b"}" * 100,  # nesting bomb
        b"{not json",
    ],
)
def test_load_json_rejects(raw):
    with pytest.raises(SchemaError):
        load_json_bytes(raw)


def test_load_json_size_cap(monkeypatch):
    import core.schema as schema

    monkeypatch.setattr(schema, "MAX_JSON_BYTES", 10)
    with pytest.raises(SchemaError, match="larger"):
        schema.load_json_bytes(b'{"aaaaaaaaaaaa": 1}')


# --------------------------------------------------------------------------- uri_text


@pytest.mark.parametrize(
    "uri,expected,count",
    [
        (
            "dbname='gis' user='[REDACTED:user]' password='[REDACTED:password]' sslmode=disable",
            "dbname='gis' sslmode=disable",
            2,
        ),
        (
            "type=xyz&url=https://[REDACTED:userinfo]@t.example/{z}.png%3Fapi_key%3D[REDACTED:api_key]&zmax=19",
            "type=xyz&url=https://t.example/{z}.png&zmax=19",
            2,
        ),
        (
            "type=xyz&url=https://t.example/{z}.png?api_key=[REDACTED:api_key]&zmax=19",
            "type=xyz&url=https://t.example/{z}.png&zmax=19",
            1,
        ),
        ("https://h/x.geojson?token=[REDACTED:token]&b=1", "https://h/x.geojson?b=1", 1),
        ("https://h/x.geojson?a=1&token=[REDACTED:token]", "https://h/x.geojson?a=1", 1),
        (
            "crs=EPSG:3857&password=[REDACTED:password]&url=https://w.example/wms%3Fkey%3D%5BREDACTED%3Aapi_key%5D%26x%3D1",
            "crs=EPSG:3857&url=https://w.example/wms%3Fx%3D1",
            2,
        ),
        ("./data.gpkg|layername=a", "./data.gpkg|layername=a", 0),
    ],
)
def test_strip_redacted(uri, expected, count):
    assert strip_redacted(uri) == (expected, count)
    assert "REDACTED" not in strip_redacted(uri)[0]


def test_map_path_longest_prefix_and_boundaries():
    m = {"/data": "/new", "/data/gis": "/gis2"}
    assert map_path("/data/gis/a.gpkg", m) == ("/gis2/a.gpkg", True)
    assert map_path("/data/b.tif", m) == ("/new/b.tif", True)
    assert map_path("/database/c.gpkg", m) == ("/database/c.gpkg", False)  # not a path-segment match
    assert map_path("C:\\Data\\x.shp", {"C:/Data": "/mnt/d"}) == ("/mnt/d/x.shp", True)


@pytest.mark.parametrize("path", ["/etc/x", "C:\\x", "c:/x", "\\\\server\\share\\x"])
def test_is_absolute(path):
    assert is_absolute(path)


@pytest.mark.parametrize("path", ["./x", "x.gpkg", "../data/x.gpkg", ""])
def test_is_relative(path):
    assert not is_absolute(path)


def test_parse_map_arg():
    assert parse_map_arg("/a=/b; C:/x = /y ;") == {"/a": "/b", "C:/x": "/y"}
    with pytest.raises(ValueError):
        parse_map_arg("no-equals-sign")


# --------------------------------------------------------------------------- JSON Schema file


def _schema():
    return json.loads((ROOT / "docs" / "schema" / "docqgisproject-1.schema.json").read_text(encoding="utf-8"))


def test_schema_file_is_valid_and_matches_writer():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    model = DocModel()
    data = model_to_json_dict(model)
    jsonschema.Draft202012Validator(schema).validate(data)  # an empty project, no rebuild payload
    data["rebuild"] = good_doc()["rebuild"]
    jsonschema.Draft202012Validator(schema).validate(data)
    assert set(schema["required"]) == set(data)


@pytest.mark.parametrize(
    "case", ["resource name traversal", "bad source id", "extra key in rebuild", "unknown source kind"]
)
def test_schema_file_also_rejects(case):
    jsonschema = pytest.importorskip("jsonschema")
    data = model_to_json_dict(DocModel())
    data["rebuild"] = _mut(HOSTILE[case])["rebuild"]
    assert list(jsonschema.Draft202012Validator(_schema()).iter_errors(data))

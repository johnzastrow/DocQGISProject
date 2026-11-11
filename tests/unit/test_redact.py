"""Redaction corpus: every secret is hidden, harmless values survive, kinds are counted."""

import pytest

from core.redact import redact_mapping, redact_named_value, redact_text, secret_name_kind

# (input, secrets that must disappear, text that must survive)
CORPUS = [
    (
        "host=db.example.org port=5432 dbname='gis' user='alice' password='p@ss w0rd' sslmode=require key='id'",  # pragma: allowlist secret
        ["alice", "p@ss w0rd"],
        ["db.example.org", "key='id'", "dbname='gis'"],
    ),
    ("dbname=gis user=bob password=hunter2 host=h", ["bob", "hunter2"], ["dbname=gis", "host=h"]),
    ("password='it\\'s secret' host=h", ["it\\'s secret"], ["host=h"]),  # pragma: allowlist secret
    ("PG:dbname=gis host=h user=carol password=topsecret", ["carol", "topsecret"], ["PG:dbname=gis"]),
    ("MSSQL:server=s;database=d;UID=dave;PWD={a;b;c};trusted_connection=no", ["dave", "a;b;c"], ["server=s"]),
    (
        "type=xyz&url=https://tiles.example.com/{z}/{x}/{y}.png?api_key=ABC123&zmax=19",
        ["ABC123"],
        ["tiles.example.com", "zmax=19"],
    ),
    (
        "type=xyz&url=https://t.example.com/%7Bz%7D/%7Bx%7D/%7By%7D.png?access_token%3DTOK999&zmin=0",
        ["TOK999"],
        ["t.example.com"],
    ),
    ("https://maps.example.com/wms?SERVICE=WMS&key=K-777&LAYERS=a", ["K-777"], ["SERVICE=WMS", "LAYERS=a"]),
    # Mixed encoding, as QGIS writes it in QML: literal "@" but encoded "?" and "=".
    (
        "type=xyz&url=https://mx-user:MX-PASS@t.example.com/%7Bz%7D.png%3Fapi_key%3DMX-KEY-1&zmax=19",  # pragma: allowlist secret
        ["mx-user", "MX-PASS", "MX-KEY-1"],
        ["t.example.com", "zmax=19"],
    ),
    # The same inside XML, where "&" is "&amp;".
    (
        "<datasource>type=xyz&amp;url=https://t.example.com/%7Bz%7D.png%3Fapi_key%3DXML-KEY-2&amp;zmin=0</datasource>",
        ["XML-KEY-2"],
        ["zmin=0", "<datasource>"],
    ),
    (
        "https://zoe-u:pw42@data.example.com/file.geojson",  # pragma: allowlist secret
        ["zoe-u", "pw42"],
        ["data.example.com/file.geojson"],
    ),
    ("/vsicurl/https://bucket.example.com/a.tif?sig=SIGNATURE1&se=2030", ["SIGNATURE1"], ["se=2030"]),
    (
        "contextualWMSLegend=0&crs=EPSG:3857&http-header:Authorization=Bearer%20XYZ&url=https://h/wms",
        ["XYZ"],
        ["crs=EPSG:3857"],
    ),
    ("url=https://h/wms&authcfg=abc1234&layers=x", ["abc1234"], ["layers=x"]),
    ("crs=EPSG:4326&url=https://h/wfs&typename=t&username=frank&password=pw", ["frank", "pw"], ["typename=t"]),
    ("token=ghp_abcdefghij&other=1", ["ghp_abcdefghij"], ["other=1"]),
    ("/data/roads.gpkg|layername=roads", [], ["/data/roads.gpkg|layername=roads"]),
]


@pytest.mark.parametrize("text,secrets,keep", CORPUS)
def test_redact_text_corpus(text, secrets, keep):
    out, kinds = redact_text(text)
    for s in secrets:
        assert s not in out, f"{s!r} leaked in {out!r}"
    for k in keep:
        assert k in out, f"{k!r} should survive in {out!r}"
    assert bool(kinds) == bool(secrets)
    if secrets:
        assert "[REDACTED:" in out


def test_empty_password_is_not_counted():
    out, kinds = redact_text("host=h password='' user=")
    assert not kinds
    assert out == "host=h password='' user="


def test_postgres_key_column_is_not_a_secret():
    out, kinds = redact_text('dbname=gis key=\'gid\' table="public"."t"')
    assert "key='gid'" in out and not kinds


def test_redact_mapping_decoded_uri():
    parts = {
        "dbname": "gis",
        "host": "h",
        "username": "alice",
        "password": "s3cret",  # pragma: allowlist secret
        "key": "id",
        "url": "https://x/{z}.png?apikey=AK1",
        "nested": [{"token": "T1"}],
    }
    out, kinds = redact_mapping(parts)
    assert out["password"] == {"redacted": "password"}
    assert out["username"] == {"redacted": "user"}
    assert out["key"] == "id"
    assert "AK1" not in out["url"]
    assert out["nested"][0]["token"] == {"redacted": "token"}
    assert kinds == {"password": 1, "user": 1, "api_key": 1, "token": 1}


@pytest.mark.parametrize(
    "name,kind",
    [
        ("db_password", "password"),
        ("mapboxToken", "token"),
        ("MY_API_KEY", "api_key"),
        ("service-token", "token"),
        ("fixture_author", None),
        ("passport_number", None),
        ("region", None),
    ],
)
def test_secret_name_kind(name, kind):
    assert secret_name_kind(name) == kind


def test_redact_named_value():
    assert redact_named_value("db_password", "x")[0] == {"redacted": "password"}
    assert redact_named_value("region", "Maine")[0] == "Maine"
    value, kinds = redact_named_value("wms_url", "https://u:p@h/x")
    assert "u:p" not in value and kinds["userinfo"] == 1

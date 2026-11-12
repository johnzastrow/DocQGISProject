"""core/paths.py: how paths are written in the documentation (option `paths`)."""

import ntpath
import posixpath
from dataclasses import dataclass, field

import pytest

from core.options import DocOptions
from core.paths import PathStyle, restyle

DIR = "/home/u/maps/project/qgis"


@pytest.mark.parametrize(
    "path,relative,absolute",
    [
        ("../data/a.gpkg", "../data/a.gpkg", "/home/u/maps/project/data/a.gpkg"),
        ("./x.svg", "./x.svg", f"{DIR}/x.svg"),
        (f"{DIR}/sub/x.svg", "./sub/x.svg", f"{DIR}/sub/x.svg"),
        ("/home/u/maps/project/assets/a.svg", "../assets/a.svg", "/home/u/maps/project/assets/a.svg"),
        ("/srv/elsewhere/b.tif", "../../../../../srv/elsewhere/b.tif", "/srv/elsewhere/b.tif"),
        ("https://example.org/a.png", "https://example.org/a.png", "https://example.org/a.png"),
        ("base64:AAAA", "base64:AAAA", "base64:AAAA"),
        ("javascript:alert(4)", "javascript:alert(4)", "javascript:alert(4)"),  # a scheme, not a file
        ("postgres://h/db", "postgres://h/db", "postgres://h/db"),
        ("", "", ""),
    ],
)
def test_show(path, relative, absolute):
    assert PathStyle(DIR, "relative", posixpath).show(path) == relative
    assert PathStyle(DIR, "absolute", posixpath).show(path) == absolute


def test_text_rewrites_every_path_under_the_project_tree():
    s = PathStyle(DIR, "relative", posixpath)
    text = f'<x file="/home/u/maps/project/assets/l.svg" a="{DIR}/b.qgz"/> see {DIR}'
    assert s.text(text) == '<x file="../assets/l.svg" a="./b.qgz"/> see .'
    assert s.text(DIR) == "."
    assert s.text("/etc/hosts and 1/2/2026") == "/etc/hosts and 1/2/2026"  # outside the tree: unchanged
    assert PathStyle(DIR, "absolute", posixpath).text(text) == text


def test_never_rewrites_the_root():
    s = PathStyle("/a/b", "relative", posixpath)
    assert s.text("/usr/share/x.svg") == "/usr/share/x.svg"
    assert s.text("/a/c.svg") == "../c.svg"


def test_windows_paths():
    s = PathStyle("C:\\Users\\u\\proj", "relative", ntpath)
    assert s.show("C:\\Users\\u\\data\\x.gpkg") == "../data/x.gpkg"
    assert s.show("D:\\data\\x.gpkg") == "D:\\data\\x.gpkg"  # another drive: no relative form
    assert s.text("C:\\Users\\u\\proj\\a.svg; C:/Users/u/data/b.svg") == "./a.svg; ../data/b.svg"


def test_no_project_folder():
    s = PathStyle(None, "relative", posixpath)
    assert s.show("/x/y.gpkg") == "/x/y.gpkg" and s.text("/x/y") == "/x/y"


def test_restyle_walks_models_and_skips_payload_data():
    @dataclass
    class Doc:
        path: str = f"{DIR}/a.gpkg"
        nested: dict = field(default_factory=lambda: {"p": [f"{DIR}/b.svg"], "data_base64": f"{DIR}/zz"})

    d = restyle(Doc(), PathStyle(DIR, "relative", posixpath))
    assert d.path == "./a.gpkg" and d.nested["p"] == ["./b.svg"]
    assert d.nested["data_base64"] == f"{DIR}/zz"


def test_option_validation():
    assert DocOptions().paths == "relative"
    assert DocOptions(paths="absolute").validate().paths == "absolute"
    with pytest.raises(ValueError):
        DocOptions(paths="full").validate()
    with pytest.raises(ValueError):
        PathStyle(DIR, "sideways")

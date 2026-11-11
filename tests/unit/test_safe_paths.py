"""OutputFolder writes only inside the chosen folder and never clobbers foreign files."""

import os

import pytest

from core.safe_paths import OutputExistsError, OutputFolder, UnsafePathError, sanitize_name, validate_name


@pytest.mark.parametrize(
    "name",
    ["../x", "a/../../x", "/etc/passwd", "a\\b", "", ".hidden", "a\x00b", "con.txt", "a//b", "x" * 200, "sp ace.md"],
)
def test_invalid_names_rejected(name):
    with pytest.raises(UnsafePathError):
        validate_name(name)


@pytest.mark.parametrize("name", ["report.md", "project.json", "images/map_1.png", "a-b_c.1.txt"])
def test_valid_names(name):
    validate_name(name)


def test_sanitize_name():
    assert sanitize_name("<script> roads / 2024 ") == "script_roads_2024"
    assert sanitize_name("../..") == "item"
    assert sanitize_name("CON") == "item"
    assert len(sanitize_name("a" * 500)) <= 60


def test_write_and_rewrite_own_file(tmp_path):
    out = OutputFolder(tmp_path / "out")
    out.write_text("report.md", "one")
    OutputFolder(tmp_path / "out").write_text("report.md", "two")  # owned via manifest
    assert (tmp_path / "out" / "report.md").read_text() == "two"


def test_refuses_foreign_file(tmp_path):
    (tmp_path / "report.md").write_text("user's own file")
    out = OutputFolder(tmp_path)
    with pytest.raises(OutputExistsError):
        out.write_text("report.md", "x")
    assert (tmp_path / "report.md").read_text() == "user's own file"
    OutputFolder(tmp_path, overwrite=True).write_text("report.md", "x")
    assert (tmp_path / "report.md").read_text() == "x"


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlinks")
def test_refuses_symlinks(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "out"
    root.mkdir()
    os.symlink(outside, root / "images")
    os.symlink(outside / "t.txt", root / "link.md")
    out = OutputFolder(root, overwrite=True)
    with pytest.raises(UnsafePathError):
        out.write_text("images/a.png", "x")
    with pytest.raises(UnsafePathError):
        out.write_text("link.md", "x")
    assert not (outside / "a.png").exists() and not (outside / "t.txt").exists()
    os.symlink(root, tmp_path / "rootlink")
    with pytest.raises(UnsafePathError):
        OutputFolder(tmp_path / "rootlink")


def test_check_writable_fails_before_writing(tmp_path):
    (tmp_path / "project.json").write_text("foreign")
    out = OutputFolder(tmp_path)
    with pytest.raises(OutputExistsError):
        out.check_writable(["report.md", "project.json"])
    assert not (tmp_path / "report.md").exists()

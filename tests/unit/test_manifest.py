"""The build manifest must cover every module the plugin imports (no silent omissions)."""

from ._repo import ROOT, manifest

# Repo directories that are deliberately NOT shipped in the plugin zip.
NOT_SHIPPED = {"tests", "scripts", "docs", "dist", ".git", ".github", "__pycache__"}


def test_every_top_level_module_is_listed():
    files = set(manifest()["FILES"])
    modules = {p.name for p in ROOT.glob("*.py")}
    assert modules <= files, f"top-level modules missing from FILES: {sorted(modules - files)}"


def test_every_package_is_listed():
    dirs = set(manifest()["DIRS"])
    packages = {
        p.parent.name
        for p in ROOT.glob("*/__init__.py")
        if p.parent.name not in NOT_SHIPPED
    }
    assert packages <= dirs, f"packages missing from DIRS: {sorted(packages - dirs)}"


def test_listed_entries_exist():
    m = manifest()
    for f in m["FILES"]:
        assert (ROOT / f).is_file(), f"FILES entry not found: {f}"
    for d in m["DIRS"]:
        assert (ROOT / d).is_dir(), f"DIRS entry not found: {d}"


def test_every_dir_is_verified():
    m = manifest()
    verify = set(m["VERIFY"])
    for d in m["DIRS"]:
        assert any(v.startswith(d.rstrip("/") + "/") for v in verify), f"DIRS entry {d} has no VERIFY entry"
    assert {"LICENSE", "metadata.txt"} <= verify

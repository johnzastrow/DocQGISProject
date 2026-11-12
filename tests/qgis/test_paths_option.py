"""Option `paths`: relative (default) or full paths, in every output (reports, JSON, QML, QPT,
the rebuild payload) and in the rebuilder."""

import json

import pytest

TEXT_SUFFIXES = (".json", ".md", ".html", ".qml", ".qpt", ".xml")


def _texts(folder):
    for f in sorted(folder.rglob("*")):
        if f.is_file() and f.suffix in TEXT_SUFFIXES:
            yield f, f.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["layout", "styling", "sources"])
def test_relative_paths_leave_no_absolute_folder(plugin_pkg, fixtures_dir, tmp_path, name):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project

    out = tmp_path / "out"
    document_project(str(fixtures_dir / f"{name}.qgz"), str(out), DocOptions(detail="full", image_dpi=48))
    needle = str(fixtures_dir)
    leaks = [str(f.relative_to(out)) for f, text in _texts(out) if needle in text]
    assert not leaks, f"absolute project folder in {leaks}"
    pdf = (out / "report.pdf").read_bytes()
    assert needle.encode() not in pdf
    data = json.loads((out / "project.json").read_text(encoding="utf-8"))
    assert data["semantic"]["project"]["file_path"] == f"{name}.qgz"
    for lyr in data["semantic"]["layers"]:
        p = lyr["source"]["path"]
        assert p is None or p.startswith(("./", "../")), p


def test_full_paths(plugin_pkg, fixtures_dir, tmp_path):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project

    out = tmp_path / "out"
    document_project(
        str(fixtures_dir / "layout.qgz"), str(out), DocOptions(formats=("json", "markdown"), paths="absolute")
    )
    data = json.loads((out / "project.json").read_text(encoding="utf-8"))
    assert data["semantic"]["project"]["file_path"] == str(fixtures_dir / "layout.qgz")
    paths = [lyr["source"]["path"] for lyr in data["semantic"]["layers"] if lyr["source"]["path"]]
    assert paths and all(p.startswith(str(fixtures_dir)) for p in paths)
    rb = data["rebuild"]
    assert all(s["file"]["path"].startswith(str(fixtures_dir)) for s in rb["sources"] if s["kind"] == "file")
    assert all(str(fixtures_dir) in s["uri"] for s in rb["sources"] if s["kind"] == "file")
    assert rb["resources"][0]["ref"] == str(fixtures_dir / "assets" / "north.svg")
    assert f'file="{fixtures_dir / "assets" / "north.svg"}"' in rb["project_xml"]
    md = (out / "report.md").read_text(encoding="utf-8")
    assert str(fixtures_dir / "layout.qgz") in md


def test_rebuild_full_paths_needs_consent(plugin_pkg, fixtures_dir, tmp_path):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.rebuild import RebuildError, rebuild_project
    from DocQGISProject.core.runner import document_project

    out = tmp_path / "out"
    document_project(str(fixtures_dir / "basic.qgz"), str(out), DocOptions(formats=("json",), paths="absolute"))
    target = tmp_path / "rebuilt.qgz"
    with pytest.raises(RebuildError, match="allow absolute paths"):
        rebuild_project(str(out / "project.json"), str(target))
    assert not target.exists()
    result = rebuild_project(str(out / "project.json"), str(target), allow_absolute=True)
    assert target.is_file() and not result.needs_credentials

    from qgis.core import QgsProject

    project = QgsProject()
    assert project.read(str(target))
    assert all(lyr.isValid() for lyr in project.mapLayers().values())  # the data are found from anywhere
    project.clear()


def test_relative_rebuild_elsewhere_points_relative(plugin_pkg, fixtures_dir, tmp_path):
    """A relative JSON rebuilt in another folder keeps relative sources (the user moves the data
    or maps them); nothing points back at the original absolute folder."""
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.rebuild import rebuild_project
    from DocQGISProject.core.runner import document_project

    out = tmp_path / "out"
    document_project(str(fixtures_dir / "basic.qgz"), str(out), DocOptions(formats=("json",)))
    target = tmp_path / "rebuilt.qgz"
    rebuild_project(str(out / "project.json"), str(target))
    import zipfile

    xml = zipfile.ZipFile(target).read("rebuilt.qgs").decode("utf-8")
    assert str(fixtures_dir) not in xml
    assert "<datasource>./fixture_data.gpkg|layername=" in xml

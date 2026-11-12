"""Option qml_folder: each layer's style also written as <layer name>.qml into a second folder."""

import json

import pytest


def test_qml_library(plugin_pkg, fixtures_dir, tmp_path):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project

    out, lib = tmp_path / "out", tmp_path / "library"
    result = document_project(
        str(fixtures_dir / "styling.qgz"),
        str(out),
        DocOptions(formats=("json", "markdown"), images=False, qml_folder=str(lib)),
    )
    data = json.loads((out / "project.json").read_text(encoding="utf-8"))
    styled = [lyr for lyr in data["semantic"]["layers"] if (lyr.get("style") or {}).get("qml")]
    files = sorted(p.name for p in lib.glob("*.qml"))
    assert len(files) == len(styled) and files
    for lyr in styled:
        exported = lyr["style"]["qml_export"]
        name = exported.rsplit("/", 1)[-1]
        assert (lib / name).read_bytes() == (out / lyr["style"]["qml"]).read_bytes()
        assert name.lower().startswith(lyr["name"].lower().replace(" ", "_")[:5])
        assert not exported.startswith("/")  # relative (default): no absolute folder in the report
    assert sum(1 for f in result.files if f.endswith(".qml") and str(lib) in f) == len(styled)
    md = (out / "report.md").read_text(encoding="utf-8")
    assert md.count("also exported as") == len(styled)


def test_qml_keeps_full_paths_as_qgis_writes_them(qgis_app, plugin_pkg, tmp_path):
    """QGIS does not resolve relative paths when loading a QML, so QML files keep full paths
    even with paths="relative", and a style loaded from them finds its SVG file."""
    import re
    from pathlib import Path

    from qgis.core import (
        QgsMarkerSymbol,
        QgsProject,
        QgsSingleSymbolRenderer,
        QgsSvgMarkerSymbolLayer,
        QgsVectorLayer,
    )

    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project

    proj_dir = tmp_path / "proj"
    (proj_dir / "assets").mkdir(parents=True)
    svg = proj_dir / "assets" / "marker.svg"
    svg.write_bytes((Path(__file__).resolve().parents[2] / "icons" / "icon.svg").read_bytes())
    project = QgsProject()
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "svg points", "memory")
    project.addMapLayer(layer)
    sym = QgsMarkerSymbol()
    sym.changeSymbolLayer(0, QgsSvgMarkerSymbolLayer(str(svg)))
    layer.setRenderer(QgsSingleSymbolRenderer(sym))
    assert project.write(str(proj_dir / "p.qgs"))  # saved with relative paths (QGIS default)
    project.clear()

    out, lib = tmp_path / "out", tmp_path / "library"
    document_project(
        str(proj_dir / "p.qgs"), str(out), DocOptions(formats=("json",), images=False, qml_folder=str(lib))
    )
    for qml in [*lib.glob("*.qml"), *(out / "styles").glob("*.qml")]:
        paths = re.findall(r'value="([^"]*marker\.svg)"', qml.read_text(encoding="utf-8"))
        assert paths == [str(svg)], (qml.name, paths)
    fresh = QgsVectorLayer("Point?crs=EPSG:4326", "fresh", "memory")
    fresh.loadNamedStyle(str(next(lib.glob("*.qml"))))
    assert Path(fresh.renderer().symbol().symbolLayer(0).path()).is_file()


def test_qml_folder_conflict_writes_nothing(plugin_pkg, fixtures_dir, tmp_path):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project
    from DocQGISProject.core.safe_paths import OutputExistsError

    out, lib = tmp_path / "out", tmp_path / "library"
    first = document_project(
        str(fixtures_dir / "basic.qgz"),
        str(tmp_path / "probe"),
        DocOptions(formats=("json",), images=False, qml_folder=str(lib)),
    )
    victim = next(p for p in lib.glob("*.qml"))
    victim_name = victim.name
    # A folder with a file of that name the plugin did not write: refuse before writing anything.
    lib2 = tmp_path / "library2"
    lib2.mkdir()
    (lib2 / victim_name).write_text("mine", encoding="utf-8")
    with pytest.raises(OutputExistsError):
        document_project(
            str(fixtures_dir / "basic.qgz"), str(out), DocOptions(formats=("json",), images=False, qml_folder=str(lib2))
        )
    assert (lib2 / victim_name).read_text(encoding="utf-8") == "mine"
    assert not (out / "project.json").exists()
    assert first.files

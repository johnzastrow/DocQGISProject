"""QGIS integration tier. Runs only with DOCQGISPROJECT_QGIS_TEST=1 under QGIS's own Python:

    DOCQGISPROJECT_QGIS_TEST=1 PATH=/usr/bin:/bin QT_QPA_PLATFORM=offscreen \
        /usr/bin/python3 -m pytest tests/qgis -q

Gated on the env var (not on `import qgis`) so a mocked qgis can never make it run by accident.
"""

import os
import sys

import pytest

ENABLED = os.environ.get("DOCQGISPROJECT_QGIS_TEST") == "1"
QGIS_PATHS = ("/usr/share/qgis/python", "/usr/share/qgis/python/plugins")


def pytest_ignore_collect(collection_path, config):
    # Skip collecting this tier entirely when it is not enabled (no qgis import attempted).
    return not ENABLED and collection_path.suffix == ".py" and collection_path.name.startswith("test_")


@pytest.fixture(scope="session")
def qgis_app():
    for p in QGIS_PATHS:
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication

    app = QgsApplication([], True)  # GUI-enabled so QAction / QMenu work offscreen
    app.initQgis()
    yield app
    app.exitQgis()


@pytest.fixture(scope="session")
def fixtures_dir(qgis_app, tmp_path_factory):
    """Generate every fixture project once per session into a temporary folder."""
    import importlib.util
    from pathlib import Path

    gen = Path(__file__).resolve().parents[1] / "fixtures" / "make_fixtures.py"
    spec = importlib.util.spec_from_file_location("make_fixtures", gen)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path_factory.mktemp("fixtures")
    gpkg = out / "fixture_data.gpkg"
    mod.write_data(gpkg)
    (out / "assets").mkdir()
    svg = out / "assets" / "north.svg"
    svg.write_bytes(mod.REPO_ICON.read_bytes())
    mod.make_basic(out, gpkg)
    mod.make_styling(out, gpkg)
    mod.make_layout(out, gpkg, svg)
    mod.make_sources(out, gpkg)
    return out


@pytest.fixture(scope="session")
def fake_secrets():
    """The fake credentials planted in sources.qgz; none may appear in any output."""
    from pathlib import Path

    gen = Path(__file__).resolve().parents[1] / "fixtures" / "make_fixtures.py"
    text = gen.read_text(encoding="utf-8")
    start = text.index("FAKE_SECRETS = (")
    return tuple(s.strip().strip('"') for s in text[start:text.index(")", start)].split("(", 1)[1].split(","))


@pytest.fixture(scope="session")
def plugin_pkg():
    """Import the repo root as package 'DocQGISProject' (its installed name)."""
    import importlib.util
    from pathlib import Path

    if "DocQGISProject" in sys.modules:
        return sys.modules["DocQGISProject"]
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "DocQGISProject", root / "__init__.py", submodule_search_locations=[str(root)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["DocQGISProject"] = mod
    spec.loader.exec_module(mod)
    return mod

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

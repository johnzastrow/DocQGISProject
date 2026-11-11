"""core/ and render/ must stay UI-free (docs/DESIGN.md principles 4 and 5)."""

import ast

import pytest

from ._repo import ROOT

FORBIDDEN_CORE = ("qgis.gui", "qgis.utils", "qgis.PyQt.QtWidgets", "PyQt6.QtWidgets", "processing")
# Renderers read the model only: no QGIS at all (PDF output is the documented exception, added in P4).
FORBIDDEN_RENDER = ("qgis", "PyQt6", "processing")


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def _violations(folder, forbidden, allow=()):
    out = []
    for path in sorted((ROOT / folder).rglob("*.py")):
        if path.name in allow:
            continue
        for name in _imports(path):
            if any(name == f or name.startswith(f + ".") for f in forbidden):
                out.append(f"{path.relative_to(ROOT)} imports {name}")
    return out


@pytest.mark.parametrize(
    "folder,forbidden,allow",
    [
        ("core", FORBIDDEN_CORE, ()),
        ("render", FORBIDDEN_RENDER, ("pdf_out.py",)),
    ],
)
def test_no_ui_imports(folder, forbidden, allow):
    assert _violations(folder, forbidden, allow) == []

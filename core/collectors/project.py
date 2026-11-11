# SPDX-License-Identifier: GPL-2.0-or-later
"""Project-level collectors: settings, metadata, variables, relations, themes, bookmarks."""

import os

from qgis.core import QgsUnitTypes
from qgis.PyQt.QtCore import Qt

from ..model import BookmarkDoc, ProjectDoc, RelationDoc, ThemeDoc, ThemeLayer, VariableDoc
from ..redact import redact_named_value
from .common import crs_doc, enum_name, finite, rect_list


def _iso(dt):
    if dt is None or not dt.isValid():
        return None
    return dt.toString(Qt.DateFormat.ISODate)


def collect_project(project, model):
    """Fill model.project. Deliberately omits who last saved the file (personal data)."""
    path = project.fileName() or ""
    doc = ProjectDoc(
        title=project.title(),
        file_name=os.path.basename(path),
        file_path=path,
        qgis_version_saved=project.lastSaveVersion().text(),
        saved_at=_iso(project.lastSaveDateTime()),
        crs=crs_doc(project.crs()),
        ellipsoid=project.ellipsoid(),
        distance_units=QgsUnitTypes.toString(project.distanceUnits()),
        area_units=QgsUnitTypes.toString(project.areaUnits()),
        path_storage=enum_name(project.filePathStorage()),
        home_path=project.presetHomePath() or None,
        background_color=project.backgroundColor().name(),
        selection_color=project.selectionColor().name(),
        default_view_extent=rect_list(project.viewSettings().defaultViewExtent()),
    )

    md = project.metadata()
    doc.metadata = {
        "title": md.title(),
        "abstract": md.abstract(),
        "author": md.author(),
        "created": _iso(md.creationDateTime()),
        "language": md.language(),
        "keywords": {k: list(v) for k, v in md.keywords().items()},
    }

    # Macros are reported, never executed (design principle 1).
    code, _ok = project.readEntry("Macros", "/pythonCode")
    doc.has_macros = bool(code and code.strip())
    doc.macro_lines = len(code.splitlines()) if doc.has_macros else 0
    if doc.has_macros:
        model.add_problem(
            "warning", "project", f"The project contains Python macros ({doc.macro_lines} lines). They were not run."
        )

    ops = project.transformContext().coordinateOperations()
    for key, op in (ops or {}).items():
        src, dst = (key if isinstance(key, (tuple, list)) else (str(key), ""))[:2]
        doc.transform_operations.append({"source": str(src), "destination": str(dst), "operation": str(op)})

    model.project = doc
    if doc.path_storage == "Absolute":
        model.add_problem("warning", "project", "Paths are saved as absolute; the project breaks if the data move.")


def collect_variables(project, model, redact=True):
    for name, value in sorted(project.customVariables().items()):
        value = value if isinstance(value, str) else str(value)
        if redact:
            value, kinds = redact_named_value(name, value)
            model.count_redactions(kinds)
        model.variables.append(VariableDoc(name=name, value=value))


def collect_relations(project, model):
    for rel_id, rel in sorted(project.relationManager().relations().items()):
        referencing = rel.referencingLayer()
        referenced = rel.referencedLayer()
        doc = RelationDoc(
            id=rel_id,
            name=rel.name(),
            referencing_layer_id=rel.referencingLayerId(),
            referencing_layer_name=referencing.name() if referencing else None,
            referenced_layer_id=rel.referencedLayerId(),
            referenced_layer_name=referenced.name() if referenced else None,
            field_pairs=[{"referencing": a, "referenced": b} for a, b in rel.fieldPairs().items()],
            strength=enum_name(rel.strength()),
            valid=rel.isValid(),
        )
        model.relations.append(doc)
        if not doc.valid:
            model.add_problem("warning", "relations", f"Relation '{doc.name}' is not valid: {rel.validationError()}")


def collect_themes(project, model):
    themes = project.mapThemeCollection()
    for name in themes.mapThemes():
        state = themes.mapThemeState(name)
        doc = ThemeDoc(name=name)
        for rec in state.layerRecords():
            layer = rec.layer()
            if layer is None:
                continue
            doc.layers.append(
                ThemeLayer(
                    layer_id=layer.id(),
                    layer_name=layer.name(),
                    style=rec.currentStyle if rec.usingCurrentStyle else None,
                )
            )
        model.themes.append(doc)


def collect_bookmarks(project, model):
    for bm in project.bookmarkManager().bookmarks():
        ext = bm.extent()
        model.bookmarks.append(
            BookmarkDoc(
                id=bm.id(),
                name=bm.name(),
                group=bm.group(),
                extent=rect_list(ext),
                crs=ext.crs().authid() if ext.crs().isValid() else "",
                rotation=finite(bm.rotation()) or 0.0,
            )
        )

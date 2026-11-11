# SPDX-License-Identifier: GPL-2.0-or-later
"""Layer-tree and layer collectors: tree structure, sources (redacted), fields, joins, metadata."""

import os

from qgis.core import (
    QgsDataProvider,
    QgsFieldConstraints,
    QgsLayerNotesUtils,
    QgsLayerTree,
    QgsMapLayer,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)

from ..model import FieldDoc, JoinDoc, LayerDoc, SourceDoc, TreeNode
from ..redact import redact_mapping, redact_text
from ..safe_paths import sanitize_name
from .common import (
    crs_doc,
    decode_source,
    enum_name,
    finite,
    is_remote,
    plain_text,
    rect_list,
    relative_to,
    safe_message,
)


# --------------------------------------------------------------------------- layer tree


def collect_tree(project):
    """The layer tree as nested TreeNodes (group and layer nodes, in panel order)."""

    def walk(node):
        if QgsLayerTree.isGroup(node):
            doc = TreeNode(
                kind="group",
                name=node.name(),
                visible=node.itemVisibilityChecked(),
                expanded=node.isExpanded(),
                mutually_exclusive=node.isMutuallyExclusive(),
                embedded=bool(node.customProperty("embedded")),
            )
            doc.children = [walk(child) for child in node.children()]
            return doc
        return TreeNode(
            kind="layer",
            name=node.name(),
            visible=node.itemVisibilityChecked(),
            expanded=node.isExpanded(),
            layer_id=node.layerId(),
            embedded=bool(node.customProperty("embedded")),
        )

    root = walk(project.layerTreeRoot())
    root.name = ""
    return root


def ordered_layers(project):
    """Layers in layer-tree order, then any project layers not in the tree.

    layerTreeRoot().findLayers() can miss layers for some storage back ends, so the
    project's mapLayers() is always merged in (qgis-plugin skill, golden rule 3).
    """
    seen, out = set(), []
    for node in project.layerTreeRoot().findLayers():
        layer = node.layer()
        if layer is not None and layer.id() not in seen:
            seen.add(layer.id())
            out.append(layer)
    for layer_id, layer in project.mapLayers().items():
        if layer_id not in seen:
            seen.add(layer_id)
            out.append(layer)
    return out


# --------------------------------------------------------------------------- sources


def source_doc(layer, project_dir, redact=True):
    provider = layer.providerType() or ""
    raw = layer.source() or ""
    parts = decode_source(provider, raw)
    doc = SourceDoc(provider=provider, remote=is_remote(provider, raw, parts))
    path = parts.get("path")
    if isinstance(path, str) and path and not doc.remote:
        doc.path = os.path.abspath(path)
        doc.path_relative = relative_to(doc.path, project_dir)
    if redact:
        doc.uri, k1 = redact_text(raw)
        doc.parts, k2 = redact_mapping(parts)
        kinds = k1 + k2
        # Count each secret once: the URI and its decoded parts usually hold the same value.
        doc.redactions = {k: max(k1.get(k, 0), k2.get(k, 0)) for k in kinds}
    else:
        doc.uri, doc.parts = raw, parts
    return doc


def resolve_layer(layer):
    """Load the data source of a layer read with DontResolveLayers. Keeps the stored style."""
    if layer.isValid():
        return True
    layer.setDataSource(layer.source(), layer.name(), layer.providerType(), QgsDataProvider.ProviderOptions())
    return layer.isValid()


# --------------------------------------------------------------------------- fields


def _field_docs(layer):
    fields = layer.fields()
    out = []
    for i in range(fields.count()):
        f = fields.at(i)
        cons = f.constraints()
        flags = cons.constraints()
        origin = enum_name(fields.fieldOrigin(i))
        default = layer.defaultValueDefinition(i)
        doc = FieldDoc(
            index=i,
            name=f.name(),
            type_name=f.typeName(),
            variant_type=enum_name(f.type()),
            length=f.length(),
            precision=f.precision(),
            alias=f.alias(),
            comment=f.comment(),
            origin=origin.replace("Origin", ""),
            default_expression=default.expression() or None,
            default_on_update=bool(default.applyOnUpdate()),
            not_null=bool(flags & QgsFieldConstraints.Constraint.ConstraintNotNull),
            unique=bool(flags & QgsFieldConstraints.Constraint.ConstraintUnique),
            constraint_expression=cons.constraintExpression() or None,
            constraint_description=cons.constraintDescription() or None,
            widget_type=layer.editorWidgetSetup(i).type(),
        )
        if doc.origin == "Expression":
            doc.expression = layer.expressionField(i)
        out.append(doc)
    return out


def _join_docs(layer, project):
    out = []
    for join in layer.vectorJoins():
        other = project.mapLayer(join.joinLayerId())
        subset = join.joinFieldNamesSubset()
        out.append(
            JoinDoc(
                join_layer_id=join.joinLayerId(),
                join_layer_name=other.name() if other else None,
                join_field=join.joinFieldName(),
                target_field=join.targetFieldName(),
                prefix=join.prefix() or None,
                fields_subset=list(subset) if subset is not None else None,
                cached=join.isUsingMemoryCache(),
            )
        )
    return out


# --------------------------------------------------------------------------- layers


def layer_stem(index, layer):
    """Stable, safe file-name stem for a layer's artifacts: 003_layer_name."""
    return f"{index:03d}_{sanitize_name(layer.name(), 'layer', 40)}"


def collect_layer(layer, project, model, options, feedback=None, sink=None, index=1):
    """Document one layer. Failures inside are recorded on the model, never raised."""
    project_dir = os.path.dirname(project.fileName()) if project.fileName() else None
    doc = LayerDoc(id=layer.id(), name=layer.name(), layer_type=enum_name(layer.type()))
    try:
        doc.source = source_doc(layer, project_dir, redact=options.redact)
        model.count_redactions(doc.source.redactions)

        # Resolve the data only when asked, and remote sources only when explicitly allowed.
        if options.load_data and not layer.isValid():
            if doc.source.remote and not options.include_network_layers:
                model.add_problem(
                    "info",
                    "layers",
                    f"'{doc.name}' is a web or database layer and was not contacted "
                    "(enable 'include network layers' to load it).",
                    doc.id,
                )
            else:
                resolve_layer(layer)
        doc.valid = layer.isValid()
        doc.data_loaded = doc.valid
        if not doc.valid and not doc.source.remote:
            model.add_problem("warning", "layers", f"'{doc.name}': data source not found or unreadable.", doc.id)

        doc.crs = crs_doc(layer.crs())
        doc.extent = rect_list(layer.extent()) if doc.valid else None
        doc.opacity = finite(layer.opacity(), 4)
        doc.blend_mode = enum_name(layer.blendMode()).replace("CompositionMode_", "")
        if layer.hasScaleBasedVisibility():
            doc.scale_visibility = {
                "min_scale": finite(layer.minimumScale()),  # most zoomed out (denominator)
                "max_scale": finite(layer.maximumScale()),  # most zoomed in
            }

        def _r(text):  # free text can hold credentials too (a URL pasted into an abstract)
            if not text or not options.redact:
                return text or None
            red, kinds = redact_text(text)
            model.count_redactions(kinds)
            return red

        md = layer.metadata()
        doc.title = _r(md.title())
        doc.abstract = _r(md.abstract())
        doc.keywords = {k: list(v) for k, v in md.keywords().items()}
        notes = QgsLayerNotesUtils.layerNotes(layer) if QgsLayerNotesUtils.layerHasNotes(layer) else None
        doc.notes = _r(plain_text(notes)) if notes else None

        if isinstance(layer, QgsVectorLayer):
            doc.geometry_type = enum_name(layer.geometryType())
            doc.wkb_type = QgsWkbTypes.displayString(layer.wkbType())
            doc.subset_string = layer.subsetString() or None
            doc.fields = _field_docs(layer)
            doc.joins = _join_docs(layer, project)
            remote_ok = not doc.source.remote or options.include_network_layers
            if doc.valid and remote_ok:
                count = layer.featureCount()
                doc.feature_count = int(count) if count is not None and count >= 0 else None
        elif isinstance(layer, QgsRasterLayer) and doc.valid:
            dp = layer.dataProvider()
            doc.raster = {
                "band_count": layer.bandCount(),
                "width": layer.width(),
                "height": layer.height(),
                "data_type": enum_name(dp.dataType(1)) if dp and layer.bandCount() else None,
                "pixel_size": [finite(layer.rasterUnitsPerPixelX()), finite(layer.rasterUnitsPerPixelY())],
            }
    except Exception as exc:  # principle 7: record and continue with the next layer
        model.add_problem("error", "layers", f"'{doc.name}' could not be fully read: {safe_message(exc)}", doc.id)
    if sink is not None:
        from .styling import collect_style

        doc.style = collect_style(layer, model, options, sink, layer_stem(index, layer))
        if options.images and doc.data_loaded:
            from .maps import layer_thumbnail

            try:
                image = layer_thumbnail(layer, project, options.image_dpi)
                doc.thumbnail = sink.add_png(f"images/{layer_stem(index, layer)}/thumbnail.png", image)
            except Exception as exc:  # principle 7
                model.add_problem("warning", "images", f"'{doc.name}' thumbnail failed: {safe_message(exc)}", doc.id)
    return doc


def collect_layers(project, model, options, feedback=None, sink=None):
    layers = ordered_layers(project)
    for n, layer in enumerate(layers):
        if feedback is not None:
            if feedback.isCanceled():
                return False
            feedback.setProgress(10 + 80 * n / max(1, len(layers)))
        if not isinstance(layer, QgsMapLayer):
            continue
        model.layers.append(collect_layer(layer, project, model, options, feedback, sink, n + 1))
    return True

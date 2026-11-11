# SPDX-License-Identifier: GPL-2.0-or-later
"""rebuild_project(): a new QGIS project from a DocQGISProject JSON file (docs/DESIGN.md section 8).

    from DocQGISProject.core.rebuild import rebuild_project
    result = rebuild_project("/out/project.json", "/new/project.qgz",
                             source_map={"/old/data": "/new/data"}, auth_map={"s3": "ab12cd3"})

The JSON is untrusted input (design section 9). The rebuilder therefore
- validates the whole document first (core/schema.py) and refuses anything unexpected;
- never runs code: project macros, Python form-init code, project expression functions and
  Python layer actions are removed, and each removal is reported;
- refuses absolute data paths the user has not mapped (relative paths are resolved by QGIS
  against the new project, exactly as in the original);
- never overwrites: the target .qgz and its "<name>_files" folder must not exist;
- writes embedded SVG/images only into "<name>_files", under validated names, and points the
  project at them;
- never opens the data: the new project is checked by reading it with layers unresolved.

Credentials were removed when the JSON was written. They are not guessed: parameters that
held a redacted value are dropped, and `auth_map` attaches a QGIS authentication
configuration (by id) to a source instead.
"""

import os
import re
import zipfile
from dataclasses import dataclass, field

from qgis.core import Qgis, QgsProject, QgsProviderRegistry
from qgis.PyQt.QtXml import QDomDocument

from .safe_paths import FILE_MODE, OutputFolder
from .schema import SOURCE_MARKER, SchemaError, load_json_bytes, validate_rebuild_document
from .uri_text import is_absolute, map_path, strip_redacted

MAX_SOURCE_MAP = 200
AUTHCFG_RE = re.compile(r"^[A-Za-z0-9]{7}$")
# Python that QGIS can run from a project: removed on rebuild.
PYTHON_ACTION_TYPES = {"1"}  # QgsAction.ActionType.GenericPython


class RebuildError(ValueError):
    """The rebuild was refused or failed; nothing was left behind."""


@dataclass
class RebuildResult:
    project_file: str = ""
    files: list = field(default_factory=list)
    problems: list = field(default_factory=list)  # (severity, message)
    needs_credentials: list = field(default_factory=list)  # source ids


# --------------------------------------------------------------------------- options


def _check_maps(source_map, auth_map):
    source_map = dict(source_map or {})
    auth_map = dict(auth_map or {})
    if len(source_map) > MAX_SOURCE_MAP:
        raise RebuildError(f"source_map has more than {MAX_SOURCE_MAP} entries")
    for old, new in source_map.items():
        if not isinstance(old, str) or not isinstance(new, str) or not old or "\x00" in old + new:
            raise RebuildError("source_map entries must be non-empty strings (old prefix -> new prefix)")
    for sid, cfg in auth_map.items():
        if not isinstance(cfg, str) or not AUTHCFG_RE.match(cfg):
            raise RebuildError(f"auth_map[{sid!r}] is not a QGIS authentication configuration id (7 letters or digits)")
    return source_map, auth_map


def _with_authcfg(uri, provider, cfg):
    if "url=" in uri or provider in ("wms", "wfs", "wcs", "oapif", "arcgismapserver", "arcgisfeatureserver"):
        return f"{uri}&authcfg={cfg}" if uri else f"authcfg={cfg}"
    return f"{uri} authcfg={cfg}".strip()


def _resolve_source(src, source_map, auth_map, result):
    """The data source to write for one source entry."""
    provider, uri = src["provider"], src["uri"]
    info = src.get("file") or {}
    path = info.get("path") or ""
    if src["kind"] == "file" and path:
        new_path, mapped = map_path(path, source_map)
        if not mapped and is_absolute(path):
            raise RebuildError(
                f"source {src['id']} uses the absolute path {path!r}; map it with source_map "
                f"(for example {{'{os.path.dirname(path)}': '<folder on this machine>'}})"
            )
        if new_path != path:
            parts = QgsProviderRegistry.instance().decodeUri(provider, uri) or {}
            if parts.get("path") != path:
                raise RebuildError(f"source {src['id']}: the path in the URI does not match the source table")
            parts["path"] = new_path
            uri = QgsProviderRegistry.instance().encodeUri(provider, parts)
    else:
        for old, new in source_map.items():  # databases and web: plain text replacement
            if old in uri:
                uri = uri.replace(old, new)
    if src.get("redacted") or "[REDACTED:" in uri or "%5BREDACTED%3A" in uri:
        uri, removed = strip_redacted(uri)
        cfg = auth_map.get(src["id"])
        if cfg:
            uri = _with_authcfg(uri, provider, cfg)
        elif removed:
            result.needs_credentials.append(src["id"])
            result.problems.append((
                "warning",
                f"Source {src['id']} ({provider}, layers {', '.join(src['layer_ids'][:5])}) had credentials "
                "removed; add a QGIS authentication configuration with auth_map, or edit the layer source.",
            ))
        if "[REDACTED:" in uri or "%5BREDACTED%3A" in uri:
            result.problems.append(("warning", f"Source {src['id']} still holds a redaction placeholder."))
    return uri


# --------------------------------------------------------------------------- XML


def _elements(node, depth=0):
    if depth > 200:
        return
    children = node.childNodes()
    for i in range(children.count()):
        el = children.at(i).toElement()
        if not el.isNull():
            yield el
            yield from _elements(el, depth + 1)


def _set_text(el, value):
    children = el.childNodes()
    for i in reversed(range(children.count())):
        el.removeChild(children.at(i))
    el.appendChild(el.ownerDocument().createTextNode(value))


def _strip_code(doc, result):
    """Remove everything QGIS could execute as Python from the project."""
    root = doc.documentElement()
    removed = []
    props = root.firstChildElement("properties")
    labels = {"Macros": "project macros", "ExpressionFunctions": "project expression functions"}
    if not props.isNull():
        # QGIS 4 writes <properties name="Macros">; older projects a <Macros> element.
        nodes = props.childNodes()
        children = [nodes.at(i).toElement() for i in range(nodes.count()) if nodes.at(i).isElement()]
        for child in children:
            key = child.attribute("name") if child.tagName() == "properties" else child.tagName()
            if key in labels:
                props.removeChild(child)
                if labels[key] not in removed:
                    removed.append(labels[key])
    form_code = actions = 0
    for el in list(_elements(root)):
        tag = el.tagName()
        if tag in ("editforminitcode", "editforminit", "editforminitfilepath") and el.text().strip():
            _set_text(el, "")
            form_code += 1
        elif tag == "editforminitcodesource":
            _set_text(el, "0")
        elif tag == "actionsetting" and el.attribute("type") in PYTHON_ACTION_TYPES:
            el.parentNode().removeChild(el)
            actions += 1
    if form_code:
        removed.append(f"Python form-init code ({form_code} entries)")
    if actions:
        removed.append(f"{actions} Python layer actions")
    if removed:
        result.problems.append((
            "warning",
            "Removed from the rebuilt project because it could run code: " + ", ".join(removed) + ".",
        ))


def _repoint_resources(doc, refs):
    """Point attribute values equal to an embedded file's reference at the written copy."""
    if not refs:
        return
    for el in _elements(doc.documentElement()):
        attrs = el.attributes()
        for j in range(attrs.count()):
            attr = attrs.item(j).toAttr()
            if attr.value() in refs:
                attr.setValue(refs[attr.value()])


# --------------------------------------------------------------------------- main


def _read_json(json_or_path):
    if isinstance(json_or_path, dict):
        return json_or_path
    path = str(json_or_path)
    if os.path.getsize(path) > 300 * 1024 * 1024:
        raise RebuildError("the JSON file is larger than 300 MB")
    with open(path, "rb") as fh:
        return load_json_bytes(fh.read())


def _parse_xml(xml):
    doc = QDomDocument()
    res = doc.setContent(xml)
    ok = res[0] if isinstance(res, tuple) else bool(res)
    if not ok:
        detail = f" ({res[1]} at line {res[2]})" if isinstance(res, tuple) else ""
        raise RebuildError(f"the project XML in the JSON could not be parsed{detail}")
    dt = doc.doctype()
    if not dt.isNull() and dt.name() and (dt.name() != "qgis" or dt.entities().count() or dt.internalSubset().strip()):
        raise RebuildError("the project XML declares a DOCTYPE other than QGIS's own")
    if doc.documentElement().tagName() != "qgis":
        raise RebuildError("the project XML is not a QGIS project")
    return doc


def rebuild_project(json_or_path, output_path, source_map=None, auth_map=None, feedback=None):
    """Write a new .qgz from a DocQGISProject JSON document. Returns a RebuildResult."""
    source_map, auth_map = _check_maps(source_map, auth_map)
    output_path = os.path.abspath(str(output_path))
    if not output_path.lower().endswith(".qgz"):
        raise RebuildError("the output must be a .qgz file")
    out_dir, out_name = os.path.split(output_path)
    stem = out_name[:-4]
    if not os.path.isdir(out_dir):
        raise RebuildError(f"the output folder does not exist: {out_dir}")
    files_dir_name = f"{stem}_files"
    files_dir = os.path.join(out_dir, files_dir_name)
    for p in (output_path, files_dir):
        if os.path.lexists(p):
            raise RebuildError(f"{p} already exists; the rebuilder never overwrites")

    try:
        rb, resources = validate_rebuild_document(_read_json(json_or_path))
    except SchemaError as exc:
        raise RebuildError(f"the JSON was refused: {exc}") from exc
    unknown = sorted(set(auth_map) - {s["id"] for s in rb["sources"]})
    if unknown:
        raise RebuildError(f"auth_map names sources that are not in the JSON: {unknown}")

    result = RebuildResult(project_file=output_path)
    doc = _parse_xml(rb["project_xml"])
    if feedback is not None:
        feedback.setProgress(20)

    # Sources: resolve every marker (validated to be declared) before writing anything.
    resolved = {s["id"]: _resolve_source(s, source_map, auth_map, result) for s in rb["sources"]}
    markers = {SOURCE_MARKER.format(id=sid): uri for sid, uri in resolved.items()}
    for el in _elements(doc.documentElement()):
        if el.tagName() == "datasource" and el.text() in markers:
            _set_text(el, markers[el.text()])
        if el.hasAttribute("source") and el.attribute("source") in markers:
            el.setAttribute("source", markers[el.attribute("source")])
    _strip_code(doc, result)
    refs = {}
    for res in rb["resources"]:
        refs[res["ref"]] = f"./{files_dir_name}/{res['name']}"
    _repoint_resources(doc, refs)
    leftover = doc.toString(1).count("@docqgisproject:source/")
    if leftover:
        raise RebuildError(f"{leftover} data-source markers could not be resolved")
    if feedback is not None:
        feedback.setProgress(50)

    written = []
    try:
        if resources:
            folder = OutputFolder(files_dir, overwrite=False)
            for name, data in resources.items():
                written.append(folder.write_bytes(name, data))
            written.append(os.path.join(files_dir, ".docqgisproject-manifest.json"))
        qgs_name = stem + ".qgs"
        xml_bytes = doc.toString(1).encode("utf-8")
        # "xb": fail if the file appeared since the check above (never overwrite).
        with open(output_path, "xb") as fh:
            written.append(output_path)
            with zipfile.ZipFile(fh, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(qgs_name, xml_bytes)
        os.chmod(output_path, FILE_MODE)  # a normal user file, like OutputFolder writes
        _verify(output_path, doc)
    except BaseException:
        for p in reversed(written):
            try:
                os.unlink(p)
            except OSError:
                pass
        if os.path.isdir(files_dir):
            try:
                os.rmdir(files_dir)
            except OSError:
                pass
        raise
    result.files = written
    if feedback is not None:
        feedback.setProgress(100)
    return result


def _verify(path, doc):
    """Read the new project back with layers unresolved and compare the layer count."""
    layers = doc.documentElement().firstChildElement("projectlayers")
    expected = sum(1 for el in _elements(layers) if el.tagName() == "maplayer") if not layers.isNull() else 0
    project = QgsProject()
    if not project.read(path, Qgis.ProjectReadFlag.DontResolveLayers):
        raise RebuildError(f"QGIS could not read the rebuilt project: {project.error()}")
    got = len(project.mapLayers())
    project.clear()
    if got < expected:
        raise RebuildError(f"the rebuilt project has {got} layers, expected {expected}")

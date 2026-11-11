# SPDX-License-Identifier: GPL-2.0-or-later
"""Validation of a DocQGISProject JSON document before it is used to rebuild a project.

The JSON given to the rebuilder is untrusted input (docs/DESIGN.md section 9): it may have
been edited by hand or written by someone else. This module checks it with an allowlist,
before anything is parsed further or written, and rejects anything that does not match.
It never "fixes" a document.

The published JSON Schema (docs/schema/docqgisproject-1.schema.json) describes the same
document for other tools. This validator is the enforcing one: QGIS does not ship a JSON
Schema library, and the plugin has no third-party dependencies. It is stricter than the
schema where safety needs it (sizes, names, hashes, no XML DOCTYPE).

Pure Python: no QGIS imports, so it is unit-tested with a corpus of hostile documents.
"""

import base64
import binascii
import hashlib
import json
import re

from .model import SCHEMA_ID

REBUILD_FORMAT = "qgis-project-xml/1"

MAX_JSON_BYTES = 300 * 1024 * 1024
MAX_PROJECT_XML_CHARS = 200 * 1024 * 1024
MAX_SOURCES = 10000
MAX_URI_CHARS = 65536
MAX_LAYERS_PER_SOURCE = 10000
MAX_RESOURCES = 2000
MAX_RESOURCE_BYTES = 10 * 1024 * 1024
MAX_RESOURCES_TOTAL = 20 * 1024 * 1024
MAX_REF_CHARS = 4096
MAX_JSON_DEPTH = 64

SOURCE_ID_RE = re.compile(r"^s[0-9]{1,6}$")
SOURCE_MARKER = "@docqgisproject:source/{id}"
SOURCE_MARKER_RE = re.compile(r"@docqgisproject:source/(s[0-9]{1,6})")
PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
LAYER_ID_RE = re.compile(r"^[A-Za-z0-9_.:{}-]{1,200}$")
RESOURCE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
RESOURCE_EXTENSIONS = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_KINDS = ("file", "database", "web", "memory", "other")
_XML_DECL_RE = re.compile(r"(?i)<!\s*(DOCTYPE|ENTITY)")
# The one DOCTYPE QGIS writes. It names an external DTD that no parser here fetches, and has
# no internal subset, so it cannot declare entities. Every other DOCTYPE is refused.
QGIS_DOCTYPE_RE = re.compile(r"""<!DOCTYPE qgis PUBLIC ['"]http://mrcc\.com/qgis\.dtd['"] ['"]SYSTEM['"]>""")


class SchemaError(ValueError):
    """The document is not a valid DocQGISProject rebuild document. `path` locates the problem."""

    def __init__(self, path, message):
        super().__init__(f"{path}: {message}")
        self.path = path


def _no_constants(name):
    raise SchemaError("$", f"non-standard JSON constant {name} is not allowed")


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise SchemaError("$", f"duplicate key {key!r}")  # JSON parsers disagree on these: refuse
        out[key] = value
    return out


def load_json_bytes(data):
    """Parse untrusted JSON bytes with limits. Returns the document (a dict)."""
    if not isinstance(data, (bytes, bytearray)):
        raise SchemaError("$", "expected bytes")
    if len(data) > MAX_JSON_BYTES:
        raise SchemaError("$", f"document is larger than {MAX_JSON_BYTES // (1024 * 1024)} MB")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SchemaError("$", "document is not UTF-8") from exc
    try:
        doc = json.loads(text, parse_constant=_no_constants, object_pairs_hook=_unique_pairs)
    except RecursionError as exc:
        raise SchemaError("$", "document is nested too deeply") from exc
    except json.JSONDecodeError as exc:
        raise SchemaError("$", f"not valid JSON (line {exc.lineno}, column {exc.colno})") from exc
    _check_depth(doc)
    if not isinstance(doc, dict):
        raise SchemaError("$", "the top level must be an object")
    return doc


def _check_depth(value, depth=0):
    if depth > MAX_JSON_DEPTH:
        raise SchemaError("$", f"document is nested deeper than {MAX_JSON_DEPTH} levels")
    if isinstance(value, dict):
        for v in value.values():
            _check_depth(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            _check_depth(v, depth + 1)


def _req(obj, key, types, path):
    if not isinstance(obj, dict) or key not in obj:
        raise SchemaError(path, f"missing required key {key!r}")
    value = obj[key]
    # bool is an int in Python: never accept it where a number or string is wanted.
    if isinstance(value, bool) and bool not in (types if isinstance(types, tuple) else (types,)):
        raise SchemaError(f"{path}.{key}", "wrong type")
    if not isinstance(value, types):
        raise SchemaError(f"{path}.{key}", "wrong type")
    return value


def _opt(obj, key, types, path):
    if obj.get(key) is None:
        return None
    return _req(obj, key, types, path)


def _only(obj, allowed, path):
    extra = sorted(set(obj) - set(allowed))
    if extra:
        raise SchemaError(path, f"unexpected keys {extra}")


def _validate_source(src, path):
    if not isinstance(src, dict):
        raise SchemaError(path, "a source must be an object")
    _only(src, ("id", "provider", "kind", "uri", "layer_ids", "file", "redacted"), path)
    sid = _req(src, "id", str, path)
    if not SOURCE_ID_RE.match(sid):
        raise SchemaError(f"{path}.id", "must look like s1, s2, ...")
    if not PROVIDER_RE.match(_req(src, "provider", str, path)):
        raise SchemaError(f"{path}.provider", "not a provider key")
    if _req(src, "kind", str, path) not in SOURCE_KINDS:
        raise SchemaError(f"{path}.kind", f"must be one of {list(SOURCE_KINDS)}")
    uri = _req(src, "uri", str, path)
    if len(uri) > MAX_URI_CHARS or "\x00" in uri:
        raise SchemaError(f"{path}.uri", "too long or contains a NUL character")
    ids = _req(src, "layer_ids", list, path)
    if not 1 <= len(ids) <= MAX_LAYERS_PER_SOURCE:
        raise SchemaError(f"{path}.layer_ids", "must list at least one layer")
    for n, lid in enumerate(ids):
        if not isinstance(lid, str) or not LAYER_ID_RE.match(lid):
            raise SchemaError(f"{path}.layer_ids[{n}]", "not a layer id")
    _opt(src, "redacted", bool, path)
    info = _opt(src, "file", dict, path)
    if info is not None:
        fpath = f"{path}.file"
        _only(info, ("path", "exists", "size", "sha256"), fpath)
        p = _req(info, "path", str, fpath)
        if len(p) > MAX_REF_CHARS or "\x00" in p:
            raise SchemaError(f"{fpath}.path", "too long or contains a NUL character")
        _opt(info, "exists", bool, fpath)
        size = _opt(info, "size", int, fpath)
        if size is not None and size < 0:
            raise SchemaError(f"{fpath}.size", "must not be negative")
        digest = _opt(info, "sha256", str, fpath)
        if digest is not None and not SHA256_RE.match(digest):
            raise SchemaError(f"{fpath}.sha256", "not a lowercase hex SHA-256")
    return sid


def decode_resource(res, path):
    """Validate one embedded resource and return its bytes (checked against its hash)."""
    if not isinstance(res, dict):
        raise SchemaError(path, "a resource must be an object")
    _only(res, ("name", "ref", "size", "sha256", "data_base64"), path)
    name = _req(res, "name", str, path)
    if not RESOURCE_NAME_RE.match(name) or not name.lower().endswith(RESOURCE_EXTENSIONS) or ".." in name:
        raise SchemaError(f"{path}.name", f"must be a plain file name ending in one of {list(RESOURCE_EXTENSIONS)}")
    ref = _req(res, "ref", str, path)
    if not ref or len(ref) > MAX_REF_CHARS or "\x00" in ref:
        raise SchemaError(f"{path}.ref", "empty, too long or contains a NUL character")
    size = _req(res, "size", int, path)
    if not 0 <= size <= MAX_RESOURCE_BYTES:
        raise SchemaError(f"{path}.size", f"must be between 0 and {MAX_RESOURCE_BYTES} bytes")
    digest = _req(res, "sha256", str, path)
    if not SHA256_RE.match(digest):
        raise SchemaError(f"{path}.sha256", "not a lowercase hex SHA-256")
    b64 = _req(res, "data_base64", str, path)
    if len(b64) > (MAX_RESOURCE_BYTES * 4) // 3 + 8:
        raise SchemaError(f"{path}.data_base64", "larger than the per-file limit")
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SchemaError(f"{path}.data_base64", "not valid base64") from exc
    if len(data) != size:
        raise SchemaError(f"{path}.size", "does not match the data")
    if hashlib.sha256(data).hexdigest() != digest:
        raise SchemaError(f"{path}.sha256", "does not match the data")
    return data


def validate_rebuild_document(doc):
    """Check everything the rebuilder uses. Returns (rebuild_dict, {resource name: bytes})."""
    if not isinstance(doc, dict):
        raise SchemaError("$", "the top level must be an object")
    if doc.get("schema") != SCHEMA_ID:
        raise SchemaError("$.schema", f"must be {SCHEMA_ID!r}")
    rb = _req(doc, "rebuild", dict, "$")
    path = "$.rebuild"
    _only(rb, ("format", "project_file", "qgis_version", "project_xml", "sources", "resources", "notes"), path)
    if rb.get("format") != REBUILD_FORMAT:
        raise SchemaError(f"{path}.format", f"must be {REBUILD_FORMAT!r}")
    project_file = _req(rb, "project_file", str, path)
    if not 0 < len(project_file) <= 255 or any(c in project_file for c in "/\\\x00"):
        raise SchemaError(f"{path}.project_file", "must be a plain file name")
    _opt(rb, "qgis_version", str, path)
    notes = _opt(rb, "notes", list, path)
    if notes is not None and (len(notes) > 100 or not all(isinstance(n, str) and len(n) < 2000 for n in notes)):
        raise SchemaError(f"{path}.notes", "must be a short list of strings")

    xml = _req(rb, "project_xml", str, path)
    if len(xml) > MAX_PROJECT_XML_CHARS:
        raise SchemaError(f"{path}.project_xml", "larger than the 200 MB limit")
    if "\x00" in xml:
        raise SchemaError(f"{path}.project_xml", "contains a NUL character")
    if _XML_DECL_RE.search(QGIS_DOCTYPE_RE.sub("", xml, count=1)):
        # Anything beyond QGIS's own DOCTYPE can only be an entity-expansion or
        # external-entity attempt.
        raise SchemaError(f"{path}.project_xml", "a DOCTYPE or ENTITY declaration is not allowed")
    if not QGIS_DOCTYPE_RE.sub("", xml.lstrip(), count=1).lstrip().startswith(("<qgis", "<?xml")):
        raise SchemaError(f"{path}.project_xml", "is not a QGIS project document")

    sources = _req(rb, "sources", list, path)
    if len(sources) > MAX_SOURCES:
        raise SchemaError(f"{path}.sources", f"more than {MAX_SOURCES} sources")
    seen = set()
    for n, src in enumerate(sources):
        sid = _validate_source(src, f"{path}.sources[{n}]")
        if sid in seen:
            raise SchemaError(f"{path}.sources[{n}].id", f"duplicate source id {sid}")
        seen.add(sid)
    for sid in set(SOURCE_MARKER_RE.findall(xml)):
        if sid not in seen:
            raise SchemaError(f"{path}.project_xml", f"refers to undeclared source {sid}")

    resources = _req(rb, "resources", list, path)
    if len(resources) > MAX_RESOURCES:
        raise SchemaError(f"{path}.resources", f"more than {MAX_RESOURCES} resources")
    files, lowered, total = {}, set(), 0
    for n, res in enumerate(resources):
        rpath = f"{path}.resources[{n}]"
        data = decode_resource(res, rpath)
        key = res["name"].lower()  # case-insensitive file systems would merge these
        if key in lowered:
            raise SchemaError(f"{rpath}.name", "duplicate resource name")
        lowered.add(key)
        total += len(data)
        if total > MAX_RESOURCES_TOTAL:
            raise SchemaError(f"{path}.resources", f"embedded files exceed {MAX_RESOURCES_TOTAL // (1024 * 1024)} MB")
        files[res["name"]] = data
    return rb, files

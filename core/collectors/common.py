# SPDX-License-Identifier: GPL-2.0-or-later
"""Small QGIS-to-plain-data helpers shared by the collectors."""

import html
import math
import os
import re

from qgis.core import QgsProviderRegistry, QgsUnitTypes

from ..model import CrsDoc
from ..redact import redact_mapping, redact_text

# Providers whose data live on a server: never resolved unless the user opts in.
WEB_PROVIDERS = {
    "wms",
    "wfs",
    "wcs",
    "oapif",
    "arcgismapserver",
    "arcgisfeatureserver",
    "sensorthings",
    "stac",
}
DB_PROVIDERS = {"postgres", "postgresraster", "mssql", "oracle", "hana", "db2"}
_REMOTE_PATH_RE = re.compile(r"(?i)(^|[\s'\"|=])(https?|ftp)://|/vsi(curl|s3|gs|az|adls|oss|swift|hdfs|webhdfs)")


def enum_name(value):
    """Readable name of a PyQt6 / QGIS enum value (or str() of anything else)."""
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)


def finite(x, digits=None):
    """A JSON-safe float (None for NaN/inf); optionally rounded."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return round(x, digits) if digits is not None else x


def rect_list(rect):
    """[xmin, ymin, xmax, ymax] or None for an empty/null rectangle."""
    if rect is None or rect.isNull() or rect.isEmpty():
        return None
    vals = [finite(v) for v in (rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum())]
    if any(v is None for v in vals) or abs(vals[0]) > 1e300:
        return None
    return vals


def crs_doc(crs):
    if crs is None:
        return None
    if not crs.isValid():
        return CrsDoc(valid=False)
    return CrsDoc(
        authid=crs.authid(),
        description=crs.description(),
        valid=True,
        map_units=QgsUnitTypes.toString(crs.mapUnits()),
        wkt=crs.toWkt(),
    )


def plain_text(html_text):
    """Best-effort conversion of rich text (layer notes) to plain text."""
    if not html_text:
        return None
    text = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", html_text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln) or None


def is_remote(provider, source, parts):
    """True when reading this layer would contact a server (web service or database)."""
    if provider in DB_PROVIDERS:
        return True
    url = str(parts.get("url", "")) if isinstance(parts, dict) else ""
    if provider in WEB_PROVIDERS:
        return not url.lower().startswith("file:")
    return bool(_REMOTE_PATH_RE.search(source or "")) or bool(_REMOTE_PATH_RE.search(url))


def decode_source(provider, source):
    """decodeUri as a plain dict of JSON-ready values (unredacted)."""
    try:
        parts = QgsProviderRegistry.instance().decodeUri(provider, source) or {}
    except Exception:  # an exotic provider without a decoder must not stop the run
        return {}
    out = {}
    for key, value in parts.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            out[str(key)] = value
        elif isinstance(value, (list, tuple)):
            out[str(key)] = [v if isinstance(v, (str, int, float, bool)) or v is None else str(v) for v in value]
        else:
            out[str(key)] = enum_name(value)
    return out


def relative_to(path, folder):
    """Path relative to folder (with ./ prefix) when inside it, else None."""
    if not path or not folder:
        return None
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(folder))
    except ValueError:  # different drives on Windows
        return None
    if rel.startswith(".."):
        return None
    return "./" + rel.replace(os.sep, "/")


def safe_message(exc):
    """An exception message safe to put in a report (credentials redacted, length bounded)."""
    text, _ = redact_text(f"{type(exc).__name__}: {exc}")
    return text[:500]


__all__ = [
    "enum_name",
    "finite",
    "rect_list",
    "crs_doc",
    "plain_text",
    "is_remote",
    "decode_source",
    "relative_to",
    "safe_message",
    "redact_mapping",
    "redact_text",
]

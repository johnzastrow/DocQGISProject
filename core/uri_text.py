# SPDX-License-Identifier: GPL-2.0-or-later
"""Text helpers for the rebuilder: credential placeholders in URIs and path mapping.

Pure Python (no QGIS), so they are unit-tested directly.
"""

import re

_ABS_RE = re.compile(r"^(/|\\\\|[A-Za-z]:[\\/])")
_PLACEHOLDER = r"(?:\[REDACTED:[a-z_]+\]|%5BREDACTED%3A[a-z_]+%5D)"
# key=<placeholder> in a QgsDataSourceUri ("password='[REDACTED:password]'") or a URL query,
# raw or percent-encoded ("%3Fapi_key%3D[REDACTED:api_key]").
_PAIR_RE = re.compile(
    r"(?P<sep>^|\s+|&|\?|%26|%3F|%3f)(?P<key>[A-Za-z_][A-Za-z0-9_.-]{0,63})(?:=|%3D|%3d)"
    rf"(?P<q>'?){_PLACEHOLDER}(?P=q)"
)
_KV_STYLE_RE = re.compile(r"(^|&)(url|type)=")
_USERINFO_RE = re.compile(rf"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://){_PLACEHOLDER}(?:@|%40)")


def is_absolute(path):
    """True for POSIX, Windows drive and UNC paths (on any platform)."""
    return bool(_ABS_RE.match(path or ""))


def parse_map_arg(text):
    """'old=new;old2=new2' (the Processing/console form) -> dict."""
    out = {}
    for part in (text or "").split(";"):
        if not part.strip():
            continue
        if "=" not in part:
            raise ValueError(f"mapping {part!r} must be old=new")  # caller reports it
        old, new = part.split("=", 1)
        out[old.strip()] = new.strip()
    return out


# --------------------------------------------------------------------------- sources


def strip_redacted(uri):
    """Remove every parameter and user-info part that holds a redaction placeholder.

    Returns (uri, removed_count).
    """
    removed = 0

    def drop_userinfo(m):
        nonlocal removed
        removed += 1
        return m.group("scheme")

    out = _USERINFO_RE.sub(drop_userinfo, uri)

    def drop_pair(m):
        nonlocal removed
        removed += 1
        sep = m.group("sep")
        return sep if sep in ("?", "%3F", "%3f") else ""

    out = _PAIR_RE.sub(drop_pair, out)
    # Tidy a separator left with nothing to introduce. Encoded: "%3F%26next" -> "%3Fnext",
    # and "%3F" before a raw "&" or the end goes. Raw "?&" depends on the URI style: in QGIS
    # key=value&... URIs (url=...) a raw "&" separates the OUTER parameters, so the "?" goes;
    # in a plain URL the "&" belongs to the query, so "?&" folds to "?".
    out = re.sub(r"(?i)%3F%26", "%3F", out)
    out = re.sub(r"(?i)%3F(?=&|$)", "", out)
    if _KV_STYLE_RE.search(out):
        out = re.sub(r"\?(?=&|$)", "", out)
    else:
        out = re.sub(r"\?&", "?", out)
        out = re.sub(r"\?$", "", out)
    return out.strip(), removed


def map_path(path, source_map):
    """Longest matching old prefix wins. Returns (new_path, mapped?)."""
    norm = path.replace("\\", "/")
    best = None
    for old in source_map:
        o = old.replace("\\", "/")
        if norm == o or norm.startswith(o.rstrip("/") + "/"):
            if best is None or len(o) > len(best[0]):
                best = (o, source_map[old])
    if best is None:
        return path, False
    return best[1] + norm[len(best[0]) :], True

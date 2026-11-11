# SPDX-License-Identifier: GPL-2.0-or-later
"""Text formatting and escaping for the human formats (Markdown now, HTML in P4).

Every string that comes from a project (names, titles, paths, expressions) is untrusted:
it can contain Markdown or HTML that would change the report's structure or inject markup.
- md_text(): prose and table cells; escapes Markdown syntax and neutralises HTML.
- md_code(): technical values (paths, URIs, expressions, ids) as inline code spans.
"""

import math
import re

# Underscores only matter for emphasis at word boundaries (GFM ignores intraword "_").
_MD_ESCAPE_RE = re.compile(r"([\\`*\[\]|~#]|(?<![A-Za-z0-9])_|_(?![A-Za-z0-9]))")
_ENTITY_RE = re.compile(r"&(?=[#A-Za-z0-9]+;)")


def _one_line(text):
    return re.sub(r"\s*[\r\n]+\s*", " ", str(text)).strip()


def md_text(value):
    """Escape untrusted text for Markdown prose or a table cell (single line, never line-initial).

    "<" becomes "&lt;" so no HTML tag can form; Markdown syntax characters are backslashed.
    """
    if value is None:
        return ""
    s = _one_line(value)
    s = _ENTITY_RE.sub("&amp;", s)  # stop "&lt;" in the data from rendering as "<"
    s = s.replace("<", "&lt;")
    return _MD_ESCAPE_RE.sub(r"\\\1", s)


def md_code(value):
    """Untrusted text as an inline code span (safe inside a table cell)."""
    if value is None or value == "":
        return ""
    s = _one_line(value).replace("|", "\\|")
    longest = max((len(m) for m in re.findall(r"`+", s)), default=0)
    fence = "`" * (longest + 1)
    if s.startswith("`") or s.endswith("`"):
        s = f" {s} "
    return f"{fence}{s}{fence}"


def fmt_bool(value):
    return "Yes" if value else "No"


def fmt_number(value, digits=6):
    if value is None:
        return "Not set"
    if isinstance(value, bool):
        return fmt_bool(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "Not set"
        if value.is_integer() and abs(value) < 1e15:
            return f"{int(value):,}"
        return f"{value:.{digits}g}"
    return md_text(value)


def fmt_extent(extent, digits=3):
    if not extent:
        return "Not set"
    xmin, ymin, xmax, ymax = extent
    return f"{xmin:.{digits}f}, {ymin:.{digits}f} to {xmax:.{digits}f}, {ymax:.{digits}f}"


def fmt_scale(denominator):
    if not denominator:
        return "None"
    return f"1:{int(round(denominator)):,}"


def fmt_redacted_or_text(value, code=True):
    """A value that may be a {"redacted": kind} placeholder."""
    if isinstance(value, dict) and "redacted" in value:
        return f"*redacted ({md_text(value['redacted'])})*"
    if value is None or value == "":
        return "Not set"
    return md_code(value) if code else md_text(value)

"""Readability lint for the human reports (docs/DESIGN.md section 6b, rule 7). Pure Python."""

import re

MAX_TABLE_COLUMNS = 6
MAX_HEADING_LEVEL = 5
_REPR_RE = re.compile(r"\{'[^']*':|\{\"[^\"]*\":|<Qgs\w+[: ]|<qgis\.|PyQt6\.|object at 0x")


def _cells(row):
    # Split a table row on unescaped pipes, ignoring the outer ones.
    return re.split(r"(?<!\\)\|", row.strip().strip("|"))


def strip_code_spans(line):
    """Remove `code` spans (any fence length) from one Markdown line."""
    return re.sub(r"(`+)(?:(?!\1).)*?\1", "", line)


def lint_markdown(text):
    """Return a list of problems; empty means the report passes."""
    problems = []
    in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#+) ", line)
        if m and len(m.group(1)) > MAX_HEADING_LEVEL:
            problems.append(f"line {n}: heading deeper than {MAX_HEADING_LEVEL}")
        if line.startswith("|") and len(_cells(line)) > MAX_TABLE_COLUMNS:
            problems.append(f"line {n}: table wider than {MAX_TABLE_COLUMNS} columns")
        if _REPR_RE.search(line):
            problems.append(f"line {n}: raw dict or Python repr: {line[:80]}")
        if re.search(r"!\[\]\(", line):
            problems.append(f"line {n}: image without alt text")
        # Code spans show their content literally (CommonMark), so only text outside them counts.
        if re.search(r"<(script|iframe|img|a|div|span|style)\b", strip_code_spans(line), re.I):
            problems.append(f"line {n}: raw HTML tag: {line[:80]}")
    return problems

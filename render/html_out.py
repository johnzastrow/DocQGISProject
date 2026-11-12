# SPDX-License-Identifier: GPL-2.0-or-later
"""Human output: one self-contained HTML file (docs/DESIGN.md section 8).

The HTML is converted from the plugin's own Markdown report, so both always carry the same
content. The converter understands only the Markdown subset render/md_out.py writes: headings,
paragraphs, pipe tables, bullet and numbered lists, **bold**, *italic*, `code` and images.
There are no links and no raw HTML in that subset, so nothing from a project can become markup.

Safety (design section 9):
- every text run is HTML-escaped after Markdown escapes are resolved;
- image sources must match the plugin's own artifact names (no URLs, no "javascript:");
- images are embedded as data URIs up to EMBED_CAP_BYTES in total, then linked relatively;
- no JavaScript at all; a strict Content-Security-Policy whose style-src is the hash of the
  one inline stylesheet, and no network sources.
"""

import base64
import hashlib
import html
import re

EMBED_CAP_BYTES = 8 * 1024 * 1024
_IMG_SRC_RE = re.compile(r"^(images|layouts)/[A-Za-z0-9][A-Za-z0-9._/-]{0,240}\.png$")
_MD_PUNCT = set("\\`*_{}[]()#+-.!|~<>&")

CSS = """
:root{--fg:#1d1f21;--muted:#5b6066;--line:#d0d4d8;--bg:#ffffff;--code:#f3f4f6;--accent:#2f5d50}
@media (prefers-color-scheme:dark){:root{--fg:#e6e6e6;--muted:#a4a9ae;--line:#3a3f44;--bg:#16181a;--code:#24272a;--accent:#8cc4b1}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{display:flex;gap:2rem;max-width:1400px;margin:0 auto;padding:1rem}
nav.toc{flex:0 0 260px;position:sticky;top:1rem;align-self:flex-start;max-height:95vh;overflow:auto;font-size:13px}
nav.toc ul{list-style:none;padding-left:.8rem;margin:.2rem 0}
nav.toc a{color:var(--accent);text-decoration:none}
main{flex:1;min-width:0}
h1{font-size:1.7rem}h2{border-bottom:2px solid var(--line);padding-bottom:.2rem;margin-top:2.2rem}
h3{display:inline;font-size:1.15rem}h4{margin-bottom:.3rem}h5{font-size:.95rem;margin:.9rem 0 .3rem}
details{border:1px solid var(--line);border-radius:6px;padding:.4rem .8rem;margin:.8rem 0}
summary{cursor:pointer}
.tw{overflow-x:auto}
table{border-collapse:collapse;margin:.5rem 0;font-size:13px}
th,td{border:1px solid var(--line);padding:.25rem .5rem;text-align:left;vertical-align:top}
th{background:var(--code)}
code{background:var(--code);padding:0 .25rem;border-radius:3px;font-size:12.5px;word-break:break-word}
img{max-width:100%;height:auto;vertical-align:middle}
td img{max-height:64px}
@media (max-width:900px){.wrap{display:block}nav.toc{position:static;max-height:none}}
@media print{nav.toc{display:none}.wrap{display:block;padding:0}details{border:0;padding:0}
summary{list-style:none}h2{break-before:page}table,img{break-inside:avoid}body{font-size:11px}
.tw{overflow:visible}}
""".strip()


def _csp():
    digest = base64.b64encode(hashlib.sha256(CSS.encode("utf-8")).digest()).decode("ascii")
    return (
        "default-src 'none'; img-src 'self' data: file:; "
        f"style-src 'sha256-{digest}'; base-uri 'none'; form-action 'none'"
    )


def _slug(text, used):
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "section"
    slug, n = base, 2
    while slug in used:
        slug, n = f"{base}-{n}", n + 1
    used.add(slug)
    return slug


# --------------------------------------------------------------------------- inline


def _flush(buf, out):
    if buf:
        # Markdown text may hold entities md_text produced (&lt; &amp;): decode, then escape all.
        out.append(html.escape(html.unescape("".join(buf))))  # quotes too: defence in depth
        buf.clear()


def inline(text, image):
    """Convert one line of the Markdown subset to HTML. `image(src, alt)` returns <img> HTML or ""."""
    out, buf = [], []
    i, n = 0, len(text)
    bold = italic = False
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and text[i + 1] in _MD_PUNCT:
            # A backslash escape is a literal character (escape &, <, > right away).
            buf.append(html.escape(text[i + 1]) if text[i + 1] in "&<>" else text[i + 1])
            i += 2
            continue
        if c == "`":
            m = re.match(r"`+", text[i:])
            fence = m.group(0)
            end = text.find(fence, i + len(fence))
            if end != -1:
                _flush(buf, out)
                code = text[i + len(fence) : end]
                if code.startswith(" ") and code.endswith(" ") and len(code) > 1:
                    code = code[1:-1]
                out.append("<code>" + html.escape(code.replace("\\|", "|")) + "</code>")
                i = end + len(fence)
                continue
        if c == "!" and text.startswith("![", i):
            m = re.match(r"!\[((?:\\.|[^\]\\])*)\]\(([^)\s]+)\)", text[i:])
            if m:
                _flush(buf, out)
                alt = re.sub(r"\\(.)", r"\1", m.group(1))
                out.append(image(m.group(2), html.unescape(alt)))
                i += len(m.group(0))
                continue
        if text.startswith("**", i):
            _flush(buf, out)
            out.append("</strong>" if bold else "<strong>")
            bold = not bold
            i += 2
            continue
        if c == "*":
            _flush(buf, out)
            out.append("</em>" if italic else "<em>")
            italic = not italic
            i += 1
            continue
        buf.append(c)
        i += 1
    _flush(buf, out)
    if italic:
        out.append("</em>")
    if bold:
        out.append("</strong>")
    return "".join(out)


def _cells(row):
    """Split a pipe-table row on unescaped pipes (pipes in code spans are always escaped)."""
    return [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))] if row.strip() != "|" else []


# --------------------------------------------------------------------------- blocks


def markdown_to_html(md, image, collapsible=True):
    """Convert the report Markdown to HTML body content. Returns (body_html, toc_entries)."""
    lines = md.splitlines()
    out, toc, used = [], [], set()
    in_details = in_section = False
    i = 0

    def close_details():
        nonlocal in_details
        if in_details:
            out.append("</details>")
            in_details = False

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = re.match(r"^(#{1,5}) (.*)$", line)
        if m:
            level, text = len(m.group(1)), m.group(2)
            plain = html.unescape(re.sub(r"\\(.)", r"\1", text))
            slug = _slug(plain, used)
            if level == 2:
                close_details()
                if in_section:
                    out.append("</section>")
                out.append("<section>")
                in_section = True
                toc.append((2, slug, plain))
            if level == 3:
                toc.append((3, slug, plain))
                if collapsible:
                    close_details()
                    out.append(f'<details open><summary><h3 id="{slug}">{inline(text, image)}</h3></summary>')
                    in_details = True
                    i += 1
                    continue
            out.append(f'<h{level} id="{slug}">{inline(text, image)}</h{level}>')
            i += 1
            continue
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|(\s*-{3,}\s*\|)+$", lines[i + 1].strip()):
            head = _cells(line)
            rows = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            parts = ['<div class="tw"><table><thead><tr>']
            parts += [f"<th>{inline(h, image)}</th>" for h in head]
            parts.append("</tr></thead><tbody>")
            for row in rows:
                parts.append("<tr>" + "".join(f"<td>{inline(c, image)}</td>" for c in row) + "</tr>")
            parts.append("</tbody></table></div>")
            out.append("".join(parts))
            continue
        if re.match(r"^\s*- ", line) or re.match(r"^\d+\. ", line):
            ordered = bool(re.match(r"^\d+\. ", line))
            items = []
            while i < len(lines) and (re.match(r"^\s*- ", lines[i]) if not ordered else re.match(r"^\d+\. ", lines[i])):
                raw = lines[i]
                depth = (len(raw) - len(raw.lstrip(" "))) // 2
                body = re.sub(r"^\s*(- |\d+\. )", "", raw)
                items.append((depth, body))
                i += 1
            tag = "ol" if ordered else "ul"
            parts, depth_now = [f"<{tag}>"], 0
            for n, (depth, body) in enumerate(items):
                while depth > depth_now:
                    parts.append(f"<{tag}>")
                    depth_now += 1
                while depth < depth_now:
                    parts.append(f"</li></{tag}>")
                    depth_now -= 1
                if n and parts[-1] not in (f"<{tag}>",):
                    parts.append("</li>")
                parts.append(f"<li>{inline(body, image)}")
            parts.append("</li>")
            parts.extend([f"</{tag}></li>"] * depth_now)
            parts.append(f"</{tag}>")
            out.append("".join(parts))
            continue
        out.append(f"<p>{inline(line, image)}</p>")
        i += 1
    close_details()
    if in_section:
        out.append("</section>")
    return "\n".join(out), toc


def _toc_html(toc):
    parts, open_sub = ['<nav class="toc"><strong>Contents</strong><ul>'], False
    for level, slug, text in toc:
        entry = f'<li><a href="#{slug}">{html.escape(text, quote=False)}</a>'
        if level == 2:
            if open_sub:
                parts.append("</ul></li>")
                open_sub = False
            elif len(parts) > 1:
                parts.append("</li>")
            parts.append(entry)
        else:
            if not open_sub:
                parts.append("<ul>")
                open_sub = True
            parts.append(entry + "</li>")
    parts.append("</ul></li>" if open_sub else "</li>")
    parts.append("</ul></nav>")
    return "".join(parts)


def render_html(model, assets=None, embed_cap=EMBED_CAP_BYTES):
    """The full HTML document. `assets` maps artifact names to bytes (for data URIs)."""
    from .md_out import render_markdown

    assets = assets or {}
    budget = [embed_cap]

    def image(src, alt):
        if not _IMG_SRC_RE.match(src) or ".." in src:
            return ""  # never emit a source the plugin did not create
        data = assets.get(src)
        if data is not None and len(data) <= budget[0]:
            budget[0] -= len(data)
            url = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        else:
            url = src
        return f'<img src="{html.escape(url)}" alt="{html.escape(alt)}" loading="lazy">'

    body, toc = markdown_to_html(render_markdown(model), image)
    p = model.project
    title = html.escape(f"Project documentation: {p.title or p.file_name or 'Untitled project'}")
    return (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{_csp()}">'
        '<meta name="referrer" content="no-referrer">'
        f'<meta name="generator" content="DocQGISProject"><title>{title}</title>'
        f'<style>{CSS}</style></head><body><div class="wrap">{_toc_html(toc)}<main>{body}</main></div></body></html>\n'
    )

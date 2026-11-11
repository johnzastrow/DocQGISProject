"""HTML converter and renderer: escaping, structure, image allowlist, CSP, embedding cap."""

import base64
import hashlib
import re

from core.model import DocModel, LayerDoc, ProjectDoc, SourceDoc
from render.html_out import CSS, inline, markdown_to_html, render_html

from ..html_safety import check_html

HOSTILE = '<img src=x onerror=alert(1)> </style><script>alert(2)</script> "quotes" & &lt;'


def _no_image(src, alt):
    return f"[img {src} {alt}]"


def test_inline_escapes_everything():
    out = inline("**bold** *it* `a|b \\| c` \\*lit\\* x &lt;y &amp;lt; a & b", _no_image)
    assert out == "<strong>bold</strong> <em>it</em> <code>a|b | c</code> *lit* x &lt;y &amp;lt; a &amp; b"


def test_inline_hostile_text_stays_text():
    from render.text import md_code, md_text

    for md in (md_text(HOSTILE), md_code(HOSTILE)):
        out = inline(md, _no_image)
        assert "<img" not in out and "<script" not in out and "</style" not in out
        assert "&lt;script&gt;" in out


def test_blocks():
    md = "# T\n\n## 1. A\n\npara\n\n| H1 | H2 |\n|---|---|\n| a \\| b | `c\\|d` |\n\n- x\n  - y\n- z\n\n1. one\n2. two\n\n### 1.1 Sub\n\ntext\n"
    body, toc = markdown_to_html(md, _no_image)
    assert "<td>a | b</td><td><code>c|d</code></td>" in body
    assert "<ul><li>x<ul><li>y</li></ul></li><li>z</li></ul>" in body
    assert "<ol><li>one</li><li>two</li></ol>" in body
    assert '<details open><summary><h3 id="1-1-sub">1.1 Sub</h3></summary>' in body
    assert [t[0] for t in toc] == [2, 3]


def _model(images):
    m = DocModel()
    m.options = {"redact": True, "detail": "standard"}
    m.project = ProjectDoc(title=HOSTILE, overview_image=images[0])
    lyr = LayerDoc(id="l", name=HOSTILE, layer_type="Vector", source=SourceDoc(provider="ogr", uri="x"))
    lyr.thumbnail = images[1]
    m.layers.append(lyr)
    return m


def test_render_html_is_safe_and_embeds_within_cap():
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    good = ["images/project_overview.png", "images/001_x/thumbnail.png"]
    text = render_html(_model(good), {good[0]: png, good[1]: png}, embed_cap=len(png))
    assert check_html(text) == []
    assert text.count("data:image/png;base64,") == 1  # the cap allowed one embed
    assert 'src="images/001_x/thumbnail.png"' in text  # the other is linked
    digest = base64.b64encode(hashlib.sha256(CSS.encode()).digest()).decode()
    assert f"style-src 'sha256-{digest}'" in text


def test_render_html_drops_foreign_image_sources():
    bad = ["javascript:alert(1)", "../../etc/passwd.png"]
    text = render_html(_model(bad), {})
    assert check_html(text) == []
    assert "javascript:" not in re.sub(r"<[^>]*>", "", text.split("<main>")[0])
    assert "<img" not in text

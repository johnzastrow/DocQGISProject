# SPDX-License-Identifier: GPL-2.0-or-later
"""Human output: PDF via QTextDocument and QPdfWriter (QtWebEngine is not in QGIS builds).

Same content as the Markdown and HTML reports: the report Markdown is converted with the HTML
converter in a simplified, non-collapsible mode that QTextDocument understands. Images are
handed to QTextDocument as in-memory resources, so it never loads anything from disk or network.
Pages get a running header (the project title) and a "Page n of N" footer.

Navigation: the plain chapter list at the top of the report is replaced by a contents table of
chapters, layers and layouts with page numbers; every entry is a link Qt writes as a PDF link to
a named destination (the heading's id). Page numbers come from a first layout pass with
placeholders of the same width, so filling them in does not move anything. Each chapter starts
a new page, and so does each layer in the Layers chapter.

This is the one renderer allowed to use Qt (tests/unit/test_core_isolation.py).
"""

import html as html_lib
import re

from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QRectF, QSizeF, Qt, QUrl
from qgis.PyQt.QtGui import (
    QFont,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTextDocument,
)

from .html_out import _IMG_SRC_RE, markdown_to_html

RESOLUTION = 96
HEADER_PX = 28
FOOTER_PX = 28

PDF_CSS = """
body{font-family:sans-serif;font-size:9pt;color:#1d1f21}
h1{font-size:16pt}h2{font-size:14pt;margin-top:10pt}h3{font-size:12pt}h4{font-size:10.5pt;margin-top:8pt}h5{font-size:9.5pt;margin-top:6pt}
table{border-collapse:collapse}th{background-color:#eef0f2}
code{font-family:monospace;background-color:#f3f4f6}
"""


TOC_PLACEHOLDER = "000"
LAYERS_CHAPTER_TITLE = "Layers"  # render/md_out.py CHAPTERS


def _breaks_and_toc(body, toc):
    """Add page breaks (every chapter, every layer) and return the TOC entries
    that get a line in the contents: chapters, layers and layouts."""
    entries, chapter = [], None
    for level, slug, text in toc:
        if level == 2:  # every chapter, the first included: the contents come before it
            chapter = text
            entries.append((2, slug, text))
            body = body.replace(f'<h2 id="{slug}">', f'<h2 id="{slug}" style="page-break-before:always">', 1)
        elif level == 3:
            entries.append((3, slug, text))
            if chapter and re.match(rf"^\d+\. {LAYERS_CHAPTER_TITLE}$", chapter):
                body = body.replace(f'<h3 id="{slug}">', f'<h3 id="{slug}" style="page-break-before:always">', 1)
    return body, entries


def _toc_html(entries, pages=None):
    rows = []
    for level, slug, text in entries:
        page = str(pages.get(slug, "")) if pages is not None else TOC_PLACEHOLDER
        indent = "" if level == 2 else "&nbsp;&nbsp;&nbsp;&nbsp;"
        weight = "font-weight:bold;" if level == 2 else ""
        rows.append(
            f'<tr><td style="{weight}">{indent}<a href="#{slug}">{html_lib.escape(text, quote=False)}</a></td>'
            f'<td align="right">{page}</td></tr>'
        )
    return (
        '<p style="font-size:13pt;font-weight:bold">Contents</p>'
        '<table width="100%" cellspacing="0" cellpadding="1">' + "".join(rows) + "</table>"
    )


def _heading_pages(doc, page_height):
    """{anchor name: 1-based page} for every anchor in the laid-out document."""
    pages = {}
    layout = doc.documentLayout()
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            names = it.fragment().charFormat().anchorNames()
            if names:
                page = int(layout.blockBoundingRect(block).top() // page_height) + 1
                for name in names:
                    pages.setdefault(name, page)
            it += 1
        block = block.next()
    return pages


def _html_for_pdf(md, assets, content_width, content_height):
    """Simplified HTML for QTextDocument. Images fit the text area (an image cannot split across pages)."""
    used, sizes = {}, {}

    def image(src, alt):
        if not _IMG_SRC_RE.match(src) or ".." in src or src not in assets:
            return ""
        if src not in sizes:
            img = QImage.fromData(assets[src])
            if img.isNull():
                return ""
            used[src] = img
            sizes[src] = (img.width(), img.height())
        w, h = sizes[src]
        width = min(w, content_width)
        if h * width / max(w, 1) > content_height:  # too tall for one page: scale down to fit
            width = int(content_height * w / max(h, 1))
        return f'<img src="{html_lib.escape(src)}" width="{max(1, width)}" alt="{html_lib.escape(alt)}">'

    body, toc = markdown_to_html(md, image, collapsible=False)
    # QTextDocument needs explicit table attributes; it ignores most CSS for tables.
    body = body.replace("<table>", '<table border="1" cellspacing="0" cellpadding="3" width="100%">')
    body = body.replace('<div class="tw">', "").replace("</table></div>", "</table>")
    body = body.replace("<section>", "").replace("</section>", "")
    body, entries = _breaks_and_toc(body, toc)
    # The first list in the report is the plain chapter list: the contents table replaces it.
    start = body.find("<ul>")
    end = body.find("</ul>", start)
    if start != -1 and end != -1:
        body = body[:start] + "{{TOC}}" + body[end + len("</ul>") :]
    else:
        body = "{{TOC}}" + body

    def page(pages=None):
        return f"<html><head><style>{PDF_CSS}</style></head><body>{body.replace('{{TOC}}', _toc_html(entries, pages))}</body></html>"

    return page, used


def render_pdf(model, assets=None):
    """The report as PDF bytes."""
    from .md_out import render_markdown

    assets = assets or {}
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buf)
    writer.setResolution(RESOLUTION)
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(15, 12, 15, 12),
            QPageLayout.Unit.Millimeter,
        )
    )
    p = model.project
    title = f"Project documentation: {p.title or p.file_name or 'Untitled project'}"
    writer.setTitle(title)
    writer.setCreator("DocQGISProject")

    page_rect = writer.pageLayout().paintRectPixels(RESOLUTION)
    width, height = page_rect.width(), page_rect.height() - HEADER_PX - FOOTER_PX

    doc = QTextDocument()
    doc.setDefaultFont(QFont("Sans Serif", 9))
    # Leave room for QTextDocument's own document margin on both sides (and a little slack).
    margin = int(doc.documentMargin()) * 2 + 8
    page_html, images = _html_for_pdf(render_markdown(model), assets, int(width) - margin, int(height) - margin - 40)
    for name, img in images.items():
        doc.addResource(QTextDocument.ResourceType.ImageResource.value, QUrl(name), img)
    doc.setPageSize(QSizeF(width, height))
    # Pass 1 with placeholder page numbers, pass 2 with the real ones (same width: no reflow).
    doc.setHtml(page_html())
    doc.setPageSize(QSizeF(width, height))
    heading_pages = _heading_pages(doc, height)
    doc.setHtml(page_html(heading_pages))
    doc.setPageSize(QSizeF(width, height))
    pages = doc.pageCount()

    painter = QPainter(writer)
    try:
        small = QFont("Sans Serif", 7)
        for i in range(pages):
            if i:
                writer.newPage()
            painter.setFont(small)
            painter.setPen(Qt.GlobalColor.darkGray)
            painter.drawText(
                QRectF(0, 0, width, HEADER_PX - 6),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                title[:120],
            )
            painter.drawLine(0, HEADER_PX - 3, int(width), HEADER_PX - 3)
            painter.drawText(
                QRectF(0, HEADER_PX + height + 4, width, FOOTER_PX - 4),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                f"Page {i + 1} of {pages}",
            )
            painter.save()
            painter.translate(0, HEADER_PX - i * height)
            doc.drawContents(painter, QRectF(0, i * height, width, height))
            painter.restore()
    finally:
        painter.end()
    buf.close()
    return bytes(data)

# SPDX-License-Identifier: GPL-2.0-or-later
"""Human output: PDF via QTextDocument and QPdfWriter (QtWebEngine is not in QGIS builds).

Same content as the Markdown and HTML reports: the report Markdown is converted with the HTML
converter in a simplified, non-collapsible mode that QTextDocument understands. Images are
handed to QTextDocument as in-memory resources, so it never loads anything from disk or network.
Pages get a running header (the project title) and a "Page n of N" footer.

This is the one renderer allowed to use Qt (tests/unit/test_core_isolation.py).
"""

import html as html_lib

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
h1{font-size:16pt}h2{font-size:13pt;margin-top:14pt}h3{font-size:11pt}h4{font-size:10pt}
table{border-collapse:collapse}th{background-color:#eef0f2}
code{font-family:monospace;background-color:#f3f4f6}
"""


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

    body, _toc = markdown_to_html(md, image, collapsible=False)
    # QTextDocument needs explicit table attributes; it ignores most CSS for tables.
    body = body.replace("<table>", '<table border="1" cellspacing="0" cellpadding="3" width="100%">')
    body = body.replace('<div class="tw">', "").replace("</table></div>", "</table>")
    body = body.replace("<section>", "").replace("</section>", "")
    return f"<html><head><style>{PDF_CSS}</style></head><body>{body}</body></html>", used


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
    html_text, images = _html_for_pdf(render_markdown(model), assets, int(width) - margin, int(height) - margin - 40)
    for name, img in images.items():
        doc.addResource(QTextDocument.ResourceType.ImageResource.value, QUrl(name), img)
    doc.setHtml(html_text)
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

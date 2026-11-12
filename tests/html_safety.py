"""Structural safety check for the HTML report (stdlib html.parser; pure Python)."""

import re
from html.parser import HTMLParser

ALLOWED_TAGS = {
    "html",
    "head",
    "meta",
    "title",
    "style",
    "body",
    "div",
    "nav",
    "main",
    "section",
    "details",
    "summary",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "p",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "strong",
    "em",
    "code",
    "img",
    "a",
}
_IMG_OK = re.compile(r"^(data:image/png;base64,[A-Za-z0-9+/=]+|(images|layouts)/[A-Za-z0-9._/-]+\.png)$")


class _Checker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems = []
        self.csp = None
        self.styles = 0

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            self.problems.append(f"tag <{tag}>")
        for name, value in attrs:
            value = value or ""
            if name.startswith("on"):
                self.problems.append(f"event handler {name} on <{tag}>")
            if name in ("href", "src", "action", "formaction", "srcset", "style"):
                if name == "href" and not value.startswith("#"):
                    self.problems.append(f"href {value[:60]!r}")
                elif name == "src" and not _IMG_OK.match(value):
                    self.problems.append(f"src {value[:60]!r}")
                elif name not in ("href", "src"):
                    self.problems.append(f"attribute {name} on <{tag}>")
        if tag == "meta" and dict(attrs).get("http-equiv") == "Content-Security-Policy":
            self.csp = dict(attrs).get("content")
        if tag == "style":
            self.styles += 1


def check_html(text):
    """Return a list of problems; empty means the document is structurally safe."""
    c = _Checker()
    c.feed(text)
    problems = list(c.problems)
    if not c.csp or "default-src 'none'" not in c.csp or "script-src" in c.csp:
        problems.append(f"missing or weak CSP: {c.csp!r}")
    if c.styles != 1:
        problems.append(f"expected exactly one <style>, found {c.styles}")
    if re.search(r"(?i)<script", text):
        problems.append("a <script> tag is present")
    return problems

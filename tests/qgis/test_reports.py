"""P4 acceptance: HTML and PDF from the same model; readability lint passes; Tier B appendix and
coverage report; hostile-project test passes for HTML."""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from html_safety import check_html  # noqa: E402
from readability import lint_markdown  # noqa: E402

FIXTURES = ("basic", "styling", "layout", "sources")


@pytest.fixture(scope="module")
def outputs(plugin_pkg, fixtures_dir, tmp_path_factory):
    from DocQGISProject.core.runner import document_project

    out = {}
    for name in FIXTURES:
        folder = tmp_path_factory.mktemp(f"rep_{name}")
        document_project(str(fixtures_dir / f"{name}.qgz"), str(folder))
        out[name] = folder
    return out


def test_all_formats_written(outputs):
    for name, folder in outputs.items():
        for f in ("project.json", "report.md", "report.html", "report.pdf"):
            assert (folder / f).is_file(), f"{name}: {f}"


@pytest.mark.parametrize("name", FIXTURES)
def test_html_is_safe_and_matches_markdown(outputs, name):
    folder = outputs[name]
    html = (folder / "report.html").read_text(encoding="utf-8")
    md = (folder / "report.md").read_text(encoding="utf-8")
    assert check_html(html) == []
    assert lint_markdown(md) == []
    # same content: every chapter heading of the Markdown appears in the HTML
    for heading in re.findall(r"^## (.+)$", md, re.M):
        assert heading in html, heading


def test_hostile_project_html(outputs, fake_secrets):
    html = (outputs["sources"] / "report.html").read_text(encoding="utf-8")
    assert check_html(html) == []
    # check_html parses real tags and attributes: no event handlers, no foreign hrefs or srcs.
    # Escaped text and quoted alt text may still mention "onerror"; that is inert.
    assert not re.search(r"<script|href=\"javascript", html, re.I)
    assert html.count("</style>") == 1  # the hostile label could not close the stylesheet
    assert "&lt;script&gt;alert(3)&lt;/script&gt;" in html  # shown as text, inert
    for secret in fake_secrets:
        assert secret not in html


def test_pdf_is_valid(outputs):
    for name, folder in outputs.items():
        data = (folder / "report.pdf").read_bytes()
        assert data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF"), name
        pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
        assert pages >= 2, f"{name}: {pages} pages"


def test_coverage_report(outputs):
    data = json.loads((outputs["styling"] / "project.json").read_text(encoding="utf-8"))
    cov = data["coverage"]
    assert 0 < cov["percent_claimed"] <= 100
    assert cov["claimed_elements"] <= cov["total_elements"]
    groups = {g["group"] for g in cov["unclaimed_groups"]}
    assert "Layouts" not in groups and "projectlayers/maplayer/renderer-v2" not in groups
    assert data["tier_b"] == []  # standard detail: no appendix rows
    md = (outputs["styling"] / "report.md").read_text(encoding="utf-8")
    assert "Appendix: coverage of the project file" in md and "full* detail level" in md


def test_tier_b_full_detail_is_redacted(plugin_pkg, fixtures_dir, tmp_path, fake_secrets):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project

    document_project(str(fixtures_dir / "sources.qgz"), str(tmp_path), DocOptions(detail="full"))
    data = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert data["tier_b"] and all(e["path"] and e["count"] >= 1 for e in data["tier_b"])
    for f in tmp_path.rglob("*"):
        if f.is_file() and f.suffix in (".json", ".md", ".html"):
            text = f.read_text(encoding="utf-8")
            for secret in fake_secrets:
                assert secret not in text, f"{secret} in {f.name}"
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Unexplained elements (Tier B)" in md
    assert lint_markdown(md) == []
    assert check_html((tmp_path / "report.html").read_text(encoding="utf-8")) == []


def test_detail_levels_change_length(plugin_pkg, fixtures_dir, tmp_path):
    from DocQGISProject.core.options import DocOptions
    from DocQGISProject.core.runner import document_project

    sizes = {}
    for level in ("summary", "standard", "full"):
        document_project(str(fixtures_dir / "styling.qgz"), str(tmp_path / level), DocOptions(detail=level, formats=("markdown",)))
        sizes[level] = len((tmp_path / level / "report.md").read_text(encoding="utf-8"))
    assert sizes["summary"] < sizes["standard"] < sizes["full"]


def test_resources(outputs):
    layout = json.loads((outputs["layout"] / "project.json").read_text(encoding="utf-8"))
    files = {f["path"].rsplit("/", 1)[-1]: f for f in layout["semantic"]["resources"]["files"]}
    assert files["north.svg"]["exists"] is True
    styling = json.loads((outputs["styling"] / "project.json").read_text(encoding="utf-8"))
    fonts = styling["semantic"]["resources"]["fonts"]
    assert fonts and all("installed" in f and f["used_by"] for f in fonts)
    sources = json.loads((outputs["sources"] / "project.json").read_text(encoding="utf-8"))
    assert any(p["section"] == "resources" and "javascript" in p["message"] for p in sources["problems"])

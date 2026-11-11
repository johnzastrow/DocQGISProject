"""metadata.txt must satisfy QGIS 4 loading and plugins.qgis.org requirements."""

import re

from ._repo import ROOT, metadata

REQUIRED = ["name", "qgisMinimumVersion", "description", "about", "version", "author", "email", "repository"]


def test_required_keys_present():
    md = metadata()
    missing = [k for k in REQUIRED if not md.get(k, "").strip()]
    assert not missing, f"missing metadata keys: {missing}"


def test_qgis4_only():
    md = metadata()
    assert md["qgisMinimumVersion"] == "4.0"
    # Without a 4.x maximum QGIS 4 refuses to load the plugin.
    assert md["qgisMaximumVersion"] == "4.99"
    assert md.getboolean("supportsQt6")


def test_processing_provider_declared():
    assert metadata()["hasProcessingProvider"].lower() == "yes"


def test_public_email_is_noreply():
    # email= is published inside the zip and on plugins.qgis.org.
    assert metadata()["email"].endswith("@users.noreply.github.com")


def test_version_is_semver_and_in_changelog():
    version = metadata()["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", version), version
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    base = version.split("-")[0]
    assert base in changelog or "## [Unreleased]" in changelog


def test_icon_exists():
    assert (ROOT / metadata()["icon"]).is_file()

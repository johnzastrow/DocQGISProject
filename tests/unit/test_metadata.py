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


SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?"
GROUPS = {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security", "Known limitations"}


def _version_key(v):
    return tuple(int(x) for x in v.split("-")[0].split("."))


def test_version_and_changelog_agree():
    """docs/RELEASING.md: metadata.txt names the latest release; the changelog starts with
    [Unreleased], then released versions newest first, each with a date."""
    version = metadata()["version"]
    assert re.fullmatch(SEMVER, version), version
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## \[([^\]]+)\](.*)$", changelog, re.M)
    assert headings[0] == ("Unreleased", ""), "the first section must be ## [Unreleased]"
    released = headings[1:]
    assert released, "no released version in CHANGELOG.md"
    for v, rest in released:
        assert re.fullmatch(SEMVER, v), v
        assert re.fullmatch(r" - \d{4}-\d{2}-\d{2}", rest), f"{v}: date missing ({rest!r})"
    keys = [_version_key(v) for v, _ in released]
    assert keys == sorted(keys, reverse=True) and len(set(keys)) == len(keys), "versions out of order"
    assert released[0][0] == version, f"metadata.txt version {version} is not the latest release {released[0][0]}"
    assert metadata()["changelog"].startswith(f"{version}:"), "metadata.txt changelog= must start with the version"
    for group in re.findall(r"^### (.+)$", changelog, re.M):
        assert group in GROUPS, group
    for v, _ in released:
        assert f"[{v}]: https://github.com/" in changelog, f"compare link for {v}"


def test_icon_exists():
    assert (ROOT / metadata()["icon"]).is_file()

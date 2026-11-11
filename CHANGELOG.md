# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- 2026-11-11: P0 scaffold. Plugin skeleton for QGIS 4 (PyQt6): `classFactory`, a Project menu entry
  ("Document Project...") that currently reports that the engine is not implemented, and an empty
  Processing provider (`docqgisproject`, shown as "Documentation"). Icon loaded from a file path.
- Build tooling from the qgis-plugin skill: `plugin_build.conf` manifest, `scripts/build_plugin.sh`
  and `scripts/build_plugin.py` (self-verifying zip), `scripts/deploy_local.sh`, `Makefile`.
- Lint and security configuration (`ruff.toml`, `setup.cfg` for flake8), GitHub Actions CI
  (ruff, flake8, Bandit, detect-secrets, unit tests, zip build) and a tag-triggered release workflow.
- Tests: pure-Python unit tier (`tests/unit`) and a QGIS tier (`tests/qgis`) gated by
  `DOCQGISPROJECT_QGIS_TEST=1`.
- Fixture generator `tests/fixtures/make_fixtures.py` that builds small synthetic projects
  (renderer types, labeling, relations, themes, a layout with each common item type, atlas, report).
- Licence: GPL-2.0-or-later (`LICENSE`).

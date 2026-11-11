# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- 2026-11-11: P1 documentation engine. `core.runner.document_project(project_or_path, output_folder,
  options, feedback)` writes `project.json` (schema `docqgisproject/1`, `semantic` part) and
  `report.md`. Covered: project settings and metadata, datum transformations, macros (reported,
  never run), layer tree (groups, visibility, mutually exclusive groups), layers in tree order
  (provider, source, CRS, extent, feature count, filter, scale visibility, opacity, blending,
  metadata title and abstract, notes), fields (type, alias, constraints, defaults, virtual-field
  expressions, widgets), joins, relations, project variables, map themes and spatial bookmarks.
- The Markdown report follows the rebuild order: overview, numbered "How to recreate this
  project" steps with QGIS menu paths, detail chapters with a "Where in QGIS" column, then
  warnings and problems.
- Credential redaction (`core.redact`), on by default: passwords, user names, tokens, API keys,
  signatures, auth-config ids and URL user information are replaced with explicit placeholders in
  URIs, decoded source parameters, variables and free text; counts are reported. Primary-key
  `key='id'` in database URIs is kept. Turning redaction off adds a warning banner.
- Safe output folder (`core.safe_paths`): allowlisted file names, no symlink traversal, atomic
  writes, and existing files are replaced only if this plugin wrote them (manifest) or the user
  chose overwrite. All target names are checked before any work starts.
- Projects given as a path are read with layers unresolved; local layers are then loaded one by
  one, and web or database layers are never contacted unless `include_network_layers` is set.
  Cancelling through `QgsFeedback` writes nothing.
- Tests: redaction corpus, safe-path and renderer unit tests with a readability lint
  (`tests/readability.py`); QGIS-tier tests run the engine on every fixture and assert that no
  planted fake credential appears in any output. New fixture `sources.qgz`.

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

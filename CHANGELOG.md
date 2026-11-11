# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- 2026-11-11: P2 styling. Every layer's renderer is documented: single symbol, categorized,
  graduated (classification method, ramp), rule-based (nested rules, filters, scales), inverted
  polygon, 2.5D, point cluster and displacement (with embedded renderer), heatmap, null; raster
  renderers (singleband pseudocolor with colour-ramp items, paletted, hillshade, singleband gray)
  with brightness, contrast, saturation and resampling.
- Every symbol layer is recorded with all its properties, the list of properties that differ
  from the default for its type, data-defined overrides (expression or field), paint effects and
  sub-symbols. The report shows only non-default settings, merges units into values, shows colours
  as hex, and lists how each class's symbol differs from the first.
- Labels: single and rule-based labeling, every setting flattened from QGIS's own XML, with the
  non-default ones shown under the Labels tab they belong to (Text, Buffer, Background, ...).
- Images: legend and symbol swatches (`images/<layer>/legend_NNN.png`), a colour-ramp bar for
  heatmaps, colour swatches for raster classes. Options `images` (default on) and `image_dpi`
  (48 to 600, default 120).
- One QML style file per layer (`styles/<layer>.qml`), referenced from the rebuild steps
  ("Load its style from ..."). Custom properties are excluded from QML.
- Generated files are held in memory until collection finishes (`core.artifacts`), with file-count
  and size budgets; cancelling still writes nothing.
- Fixtures: three "zoo" layers stacking every registered symbol-layer type (30 types), two
  GeoTIFF rasters with four raster renderers, richer labels, a join and a virtual field.

### Fixed

- Redaction missed an API key when a URL mixed a literal `@` with an encoded `%3D`, as QGIS writes
  tile URLs in QML. Both forms are now always scanned.
- QML files are redacted structurally (`core.xmlwalk.redact_dom`) instead of as text; text
  redaction read symbol-layer `pass="0"` attributes as passwords and would have corrupted styles.

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

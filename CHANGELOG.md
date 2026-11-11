# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- 2026-11-11: P4 HTML and PDF reports. All four formats are written by default
  (`project.json`, `report.md`, `report.html`, `report.pdf`).
  - HTML: one self-contained file converted from the report Markdown (same content), table of
    contents, collapsible layer and layout sections, print stylesheet, dark mode. No JavaScript;
    Content-Security-Policy with `default-src 'none'` and the stylesheet pinned by its SHA-256
    hash; images embedded as data URIs up to 8 MB in total, then linked; image sources must match
    the plugin's own file names.
  - PDF: A4 via QTextDocument and QPdfWriter, running header with the project title, "Page n of N"
    footer, images scaled to fit the text area and one page height.
- Coverage report (appendix): the share of project-file elements the chapters explain, and the
  unexplained ones grouped by section. With detail level *full*, a Tier B table lists every
  unexplained element path with counts and redacted sample values. The project XML is parsed with
  Qt's parser (bounded entity expansion), read from the .qgz in memory with a 200 MB cap.
- "Fonts and files" chapter: fonts used by labels, font markers and layout text, checked against
  the installed fonts; SVG and image files used by symbols and pictures, checked for existence.
  Missing ones are warnings.
- Detail levels now apply: *summary* omits per-setting tables (symbol layers, layout item
  settings, source parameters); *full* adds the Tier B table.
- Tests: HTML structural safety check (allowlisted tags, no event handlers, no foreign `href` or
  `src`, CSP present), hostile-project HTML fixtures (layer notes, layout name, label text,
  `javascript:` picture path), PDF validity, coverage, detail levels, resources; a unit test that
  no shipped file name matches the build's ban list.

- 2026-11-11: P3 print layouts and reports. Every layout item is documented with type, page,
  position, size, reference point, rotation, frame, background, opacity, blending, visibility,
  data-defined overrides and every attribute QGIS stores for it; type-specific settings for maps
  (extent, scale, CRS, rotation, locked layers or followed theme, atlas control, grids, overviews),
  labels, legends, scale bars, pictures (source file and whether it exists), shapes, polygons and
  polylines (nodes), markers, groups and charts. Tables and frames (attribute, fixed, text, HTML),
  pages, layout variables (redacted), atlas settings with feature count, and report sections.
- Images: each layout page, close-ups of maps, legends and scale bars at twice the image DPI, the
  first atlas page, a thumbnail per layer and a project overview map. Each image is capped at 16
  megapixels.
- Each print layout is saved as a template (`layouts/<n>_<name>.qpt`) that loads back with Layout
  Manager > New from Template; reports are saved as their XML definition. The rebuild steps now
  include creating each layout from its template.
- A "Print layouts" chapter; chapter numbers now come from one ordered list.
- Quality checks: maps with an empty extent, pictures pointing to missing files.
- Crash guard: QGIS 4.2.3 segfaults when it draws a chart item without a loaded source layer
  (`QgsLayoutItemChart::prepareGatherer`). Pages and close-ups containing such a chart are not
  rendered, and the report says why.
- Fixtures: an "Item zoo" layout with one item of every registered layout item type, an inset map
  following a theme, a layout variable.

### Fixed

- Fixture layouts set map extents before sizing the map items, so every map drew nothing; maps
  are now sized first and use `zoomToExtent`.

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

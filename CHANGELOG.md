# Changelog

All notable changes to DocQGISProject are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). What counts as a major, minor or patch change, and how
a release is made, is in [`docs/RELEASING.md`](docs/RELEASING.md).

## [Unreleased]

## [0.1.0] - 2026-11-12

First release (experimental). The detailed development log behind it is in
[`docs/CHANGELOG-pre-0.1.0.md`](docs/CHANGELOG-pre-0.1.0.md).

### Added

- **Outputs.** One run writes `project.json` (machine-readable, schema `docqgisproject/1`,
  [JSON Schema](docs/schema/docqgisproject-1.schema.json)), `report.md`, `report.html` (one
  self-contained page, no JavaScript, strict Content-Security-Policy) and `report.pdf` (A4,
  linked contents with page numbers, every chapter and every layer on a new page). Also images of
  styles, maps and layout pages, one QML style per layer and one QPT template per print layout.
- **What is documented.** Project settings, metadata, transformations and macros (reported, never
  run); the layer tree; every layer with its source, fields, joins, symbology (all renderer types
  and every symbol layer), labels, elevation and all other layer settings that differ from QGIS
  defaults, by the dialog page where each is set; relations, variables, map themes, bookmarks;
  print layouts with every item, tables, atlas and reports; fonts and files the project needs.
  The report follows the order in which you would rebuild the project, with "Where in QGIS" for
  each setting, and a coverage appendix says how much of the project file it explains.
- **Rebuilding.** A rebuilder that writes a new project from the JSON, with data folders and
  logins mapped by the user; the JSON is treated as untrusted (validated in full, macros and other
  Python code removed, nothing overwritten).
- **Using it.** A dialog (eye button on the Project toolbar, *Project > Document Project...*,
  *Plugins > DocQGISProject*) with progress, cancel, Open report and remembered options; Processing
  algorithms *Document project* and *Rebuild project from JSON*, also for `qgis_process`; the
  Python console API.
- **Options.** Formats, detail level, images and resolution, relative or full paths, loading data,
  opening web services and databases (off by default), credential redaction (on by default),
  overwrite rules, embedded SVG and images in the JSON, a QML style library in a second folder.
- **Dialog screenshots** (optional, dialog only, for the open project): Project Properties, Layer
  Properties and Layout Designer pages, placed next to the settings they show; by default only
  pages with settings that differ from QGIS defaults. Pages that show data sources or logins are
  skipped, and fields or list rows that show a path, address or login are blacked out.

### Security

- Credentials (passwords, user names, tokens, API keys, URL user information, secret-named
  variables) are removed from every output by default, structurally in XML, and counted in the
  report.
- Output files are written only inside the chosen folders, atomically, without following
  symbolic links, and existing files are replaced only if the plugin wrote them.
- Web services and databases are not contacted unless you allow it.

### Known limitations

- Dialog screenshots match dialog pages by their English titles. With QGIS in another language,
  they stay with their layer or project but appear under "Other layer settings" (or "Other project
  settings") instead of next to Symbology, Labels, Fields, Joins and Elevation, and the "only
  changed pages" choice pictures fewer pages than it should.
- QML style files keep full paths to SVG and image files even with relative paths, because QGIS
  does not resolve relative paths when it loads a QML file.
- Tested on QGIS 4.2.3 on Linux. Windows and macOS are untested.

[Unreleased]: https://github.com/johnzastrow/DocQGISProject/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/johnzastrow/DocQGISProject/releases/tag/v0.1.0

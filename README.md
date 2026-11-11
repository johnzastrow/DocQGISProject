# DocQGISProject

A QGIS 4 plugin that documents a QGIS project for two audiences from one run:

- **People:** Markdown, HTML and PDF reports, readable enough to rebuild the project by hand, with
  rendered layout pages, symbols and legends.
- **Machines:** a schema-versioned JSON file complete enough to rebuild the project programmatically.

**Status: development (phase P3).** The documentation engine writes `project.json` and `report.md`
covering project settings, the layer tree, layers and their sources (credentials redacted), fields,
joins, relations, variables, map themes, bookmarks, full styling (renderers, every symbol layer,
labels, raster rendering) and print layouts (every item with position and size, tables, atlas,
reports). Images: legend swatches, layer thumbnails and an overview map (`images/`), layout pages and
item close-ups (`layouts/`). Files to rebuild with: one QML style per layer (`styles/`) and one
template per layout (`layouts/*.qpt`). HTML and PDF (P4), the rebuilder (P5) and the dialog and
Processing algorithm (P6) are still to come.
See [`docs/DESIGN.md`](docs/DESIGN.md) for the design and delivery plan.

Until the dialog lands, run it from the QGIS Python Console:

```python
from DocQGISProject.core.runner import document_project
from DocQGISProject.core.options import DocOptions

# The open project, or a path to a .qgz/.qgs file (read without touching the open project).
result = document_project(QgsProject.instance(), "/path/to/output_folder", DocOptions())
print(result.files, result.redactions)
```

Options: `load_data` (default on: load local layers for counts and extents), `redact` (default on),
`include_network_layers` (default off: web services and databases are never contacted),
`overwrite` (default off: files in the folder that this plugin did not write are never replaced),
`images` (default on) and `image_dpi` (default 120).

Requirements: QGIS 4.0 or later (Qt 6). Licence: GPL-2.0-or-later.

## Development

```mermaid
flowchart LR
    A["make check<br/>ruff, flake8, Bandit,<br/>detect-secrets, unit tests"] --> B["make qgis-test<br/>QGIS tier (headless)"]
    B --> C["make build<br/>self-verifying zip in dist/"]
    C --> D["make deploy<br/>install into local QGIS profile"]
```

| Command | What it does |
|---|---|
| `make check` | All gates: `ruff check`, `flake8` (authoritative), `bandit`, `detect-secrets`, unit tests (`tests/unit`, pure Python) |
| `make qgis-test` | QGIS integration tier (`tests/qgis`) under QGIS's own Python, offscreen; gated by `DOCQGISPROJECT_QGIS_TEST=1` |
| `make fixtures` | Generate the synthetic test projects into `tests/fixtures/generated/` (git-ignored) |
| `make build` | Build `dist/DocQGISProject.zip` from `plugin_build.conf` and verify its contents |
| `make deploy` | Build and install into the local QGIS 4 profile (restart QGIS afterwards) |

Tools: [uv](https://docs.astral.sh/uv/) runs the linters in throwaway environments. On Ubuntu the QGIS tier
uses the system Python (`/usr/bin/python3`) with `PATH=/usr/bin:/bin`, because a different Python first on
`PATH` breaks PyQt6.

Reproduce the QGIS tier by hand:

```bash
DOCQGISPROJECT_QGIS_TEST=1 PATH=/usr/bin:/bin QT_QPA_PLATFORM=offscreen \
    /usr/bin/python3 -m pytest tests/qgis -q -p no:cacheprovider
```

## Security

The plugin is read only: it never modifies the project or its data and never runs project macros,
actions or embedded Python. Credentials in data sources are redacted from every output by default.
See section 9 of the design.

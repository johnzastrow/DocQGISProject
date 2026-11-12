# Versions and releases

DocQGISProject uses [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.
The version lives in one place, `version=` in `metadata.txt`, and always names the latest
release. Changes since then are listed under `## [Unreleased]` in `CHANGELOG.md`.

## What each part means here

The public surface is what other people and programs rely on: the JSON document, the options and
their meaning, the Processing algorithm ids and parameters, the Python API
(`core.runner.document_project`, `core.rebuild.rebuild_project`), and the report's file names.

| Bump | When | Examples |
|---|---|---|
| MAJOR | A change that breaks something built on the public surface | the JSON schema id changes (`docqgisproject/1` to `/2`); an option, Processing parameter or algorithm id is removed or renamed; a default changes so that the same call gives a different kind of output; the minimum QGIS version rises |
| MINOR | Something new that does not break existing use | a new option, output, report chapter, Processing parameter or algorithm; new fields in the JSON; more of the project file explained |
| PATCH | Fixes and improvements with no new surface | bug and security fixes, wording, performance, documentation, tests, build tooling |

While the version is `0.x`, the plugin is experimental (`experimental=True` in `metadata.txt`)
and, as semver allows, a breaking change bumps MINOR instead of MAJOR. The changelog says so in
the entry. `1.0.0` comes when the plugin leaves experimental status.

The JSON schema has its own version, the `schema` id `docqgisproject/N`. It changes only when a
program reading the JSON would break (a key removed, renamed or retyped); adding keys does not
change it. A schema change is always at least a MINOR plugin release (MAJOR from 1.0 on).

## Every change

In the same commit as a user-visible change, add a line under `## [Unreleased]` in
`CHANGELOG.md`, in the right group: Added, Changed, Deprecated, Removed, Fixed or Security.
Write for users: what changed and why it matters, not how the code changed. Internal changes
(tests, refactoring, CI) need no entry unless they change what users get.

## Making a release

1. Decide the new version from the Unreleased entries (the largest kind of change wins).
2. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [x.y.z] - YYYY-MM-DD`, add a new empty
   `## [Unreleased]` above it, and update the compare links at the bottom.
3. In `metadata.txt`, set `version=x.y.z` and replace `changelog=` with a one-line summary that
   starts with `x.y.z:` (plugins.qgis.org shows it in the plugin manager).
4. Run `make check`, `make qgis-test` and `make build`; commit as `Release x.y.z`; push.
5. Tag with `make tag V=x.y.z`. It refuses if `metadata.txt` and the changelog disagree, runs the
   gates and the build again, and pushes the tag. GitHub Actions then builds the zip and creates
   a GitHub Release with it attached (public).
6. Check the zip attached to the GitHub Release (`unzip -p ... DocQGISProject/metadata.txt`).
7. Upload that zip at https://plugins.qgis.org/plugins/DocQGISProject/version/add/ (manual).

Tagging (5) and uploading (7) are public steps: the owner decides when.

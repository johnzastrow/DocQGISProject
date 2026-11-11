# SPDX-License-Identifier: GPL-2.0-or-later
"""Run options shared by the dialog, Processing and the Python API (docs/DESIGN.md section 7).

Strict allowlist validation: unknown formats or levels are rejected, never coerced.
"""

from dataclasses import asdict, dataclass

ALL_FORMATS = ("json", "markdown", "html", "pdf")
IMPLEMENTED_FORMATS = ("json", "markdown")  # html and pdf arrive in phase P4
DETAIL_LEVELS = ("summary", "standard", "full")


@dataclass
class DocOptions:
    formats: tuple = IMPLEMENTED_FORMATS
    detail: str = "standard"
    load_data: bool = True  # resolve local layers for counts and extents
    redact: bool = True  # remove credentials from every output
    include_network_layers: bool = False  # resolve web services and databases too
    overwrite: bool = False  # replace files in the output folder not written by this plugin

    def validate(self):
        formats = tuple(self.formats)
        if not formats:
            raise ValueError("at least one output format is required")
        unknown = [f for f in formats if f not in ALL_FORMATS]
        if unknown:
            raise ValueError(f"unknown output format(s): {unknown}; allowed: {list(ALL_FORMATS)}")
        pending = [f for f in formats if f not in IMPLEMENTED_FORMATS]
        if pending:
            raise ValueError(f"format(s) not implemented yet in this development build: {pending}")
        if self.detail not in DETAIL_LEVELS:
            raise ValueError(f"unknown detail level {self.detail!r}; allowed: {list(DETAIL_LEVELS)}")
        for name in ("load_data", "redact", "include_network_layers", "overwrite"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"option {name} must be true or false")
        self.formats = formats
        return self

    def to_dict(self):
        d = asdict(self)
        d["formats"] = list(self.formats)
        return d

# SPDX-License-Identifier: GPL-2.0-or-later
"""Run options shared by the dialog, Processing and the Python API (docs/DESIGN.md section 7).

Strict allowlist validation: unknown formats or levels are rejected, never coerced.
"""

from dataclasses import asdict, dataclass

from .paths import PATH_MODES

ALL_FORMATS = ("json", "markdown", "html", "pdf")
IMPLEMENTED_FORMATS = ALL_FORMATS
DETAIL_LEVELS = ("summary", "standard", "full")
# Dialog screenshots (design 6b): GUI only. "layers" and "all" differ in which layers:
# the ones listed in screenshot_layers, or every layer.
SCREENSHOT_SCOPES = ("none", "project", "layers", "all")
# Which dialog pages to picture: only pages whose settings differ from QGIS defaults, or all.
SCREENSHOT_PAGES = ("changed", "all")
MAX_SCREENSHOT_LAYERS = 200


@dataclass
class DocOptions:
    formats: tuple = IMPLEMENTED_FORMATS
    detail: str = "standard"
    load_data: bool = True  # resolve local layers for counts and extents
    redact: bool = True  # remove credentials from every output
    include_network_layers: bool = False  # resolve web services and databases too
    overwrite: bool = False  # replace files in the output folder not written by this plugin
    images: bool = True  # legend and symbol images
    image_dpi: int = 120  # 48 to 600
    paths: str = "relative"  # "relative" to the project folder, or "absolute" (full paths); core/paths.py
    embed_resources: bool = True  # SVG and images used by styles and layouts inside the JSON
    screenshots: str = "none"  # see SCREENSHOT_SCOPES; ignored outside the QGIS window
    screenshot_layers: tuple = ()  # layer ids for screenshots == "layers"
    screenshot_pages: str = "changed"  # see SCREENSHOT_PAGES
    qml_folder: str = ""  # also write each layer's style as <layer name>.qml here ("" = off)

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
        if isinstance(self.image_dpi, bool) or not isinstance(self.image_dpi, int) or not 48 <= self.image_dpi <= 600:
            raise ValueError("image_dpi must be a whole number from 48 to 600")
        if self.paths not in PATH_MODES:
            raise ValueError(f"unknown path style {self.paths!r}; allowed: {list(PATH_MODES)}")
        if self.screenshots not in SCREENSHOT_SCOPES:
            raise ValueError(f"unknown screenshot scope {self.screenshots!r}; allowed: {list(SCREENSHOT_SCOPES)}")
        layers = tuple(self.screenshot_layers or ())
        if len(layers) > MAX_SCREENSHOT_LAYERS or not all(isinstance(x, str) and 0 < len(x) <= 200 for x in layers):
            raise ValueError(f"screenshot_layers must be up to {MAX_SCREENSHOT_LAYERS} layer ids")
        if self.screenshots == "layers" and not layers:
            raise ValueError('screenshots="layers" needs at least one layer in screenshot_layers')
        if not isinstance(self.qml_folder, str) or len(self.qml_folder) > 4096 or "\x00" in self.qml_folder:
            raise ValueError("qml_folder must be a folder path (or empty for no export)")
        if self.screenshot_pages not in SCREENSHOT_PAGES:
            raise ValueError(
                f"unknown screenshot page choice {self.screenshot_pages!r}; allowed: {list(SCREENSHOT_PAGES)}"
            )
        if self.screenshots != "none" and not self.images:
            raise ValueError("screenshots are images: they need images turned on")
        self.screenshot_layers = layers
        for name in ("load_data", "redact", "include_network_layers", "overwrite", "images", "embed_resources"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"option {name} must be true or false")
        self.formats = formats
        return self

    def to_dict(self):
        d = asdict(self)
        d["formats"] = list(self.formats)
        d["screenshot_layers"] = list(self.screenshot_layers)
        return d

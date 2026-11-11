# SPDX-License-Identifier: GPL-2.0-or-later
"""DocModel: the plain-data model collectors fill and renderers read.

Pure Python (no QGIS, no Qt). Values are JSON-ready: str, int, float, bool, None, lists,
dicts and the dataclasses below. Redacted values are {"redacted": "<kind>"} placeholders.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

SCHEMA_ID = "docqgisproject/1"


@dataclass
class Problem:
    """A warning or a collector failure. Nothing is silently missing (design principle 7)."""

    severity: str  # "error" | "warning" | "info"
    section: str
    message: str
    layer_id: Optional[str] = None


@dataclass
class CrsDoc:
    authid: str = ""
    description: str = ""
    valid: bool = False
    map_units: str = ""
    wkt: str = ""


@dataclass
class SourceDoc:
    provider: str = ""
    uri: str = ""  # redacted text
    parts: dict = field(default_factory=dict)  # decodeUri result, redacted
    remote: bool = False
    path: Optional[str] = None  # absolute local path, when the source is a file
    path_relative: Optional[str] = None  # relative to the project folder, when inside it
    redactions: dict = field(default_factory=dict)  # kind -> count


@dataclass
class FieldDoc:
    index: int
    name: str
    type_name: str = ""
    variant_type: str = ""
    length: int = 0
    precision: int = 0
    alias: str = ""
    comment: str = ""
    origin: str = ""  # Provider | Join | Expression | Edit | Unknown
    expression: Optional[str] = None  # virtual (expression) field
    default_expression: Optional[str] = None
    default_on_update: bool = False
    not_null: bool = False
    unique: bool = False
    constraint_expression: Optional[str] = None
    constraint_description: Optional[str] = None
    widget_type: str = ""


@dataclass
class JoinDoc:
    join_layer_id: str
    join_layer_name: Optional[str] = None
    join_field: str = ""
    target_field: str = ""
    prefix: Optional[str] = None
    fields_subset: Optional[list] = None
    cached: bool = False


@dataclass
class LayerDoc:
    id: str
    name: str
    layer_type: str = ""  # Vector | Raster | Mesh | VectorTile | PointCloud | ...
    valid: bool = False
    data_loaded: bool = False  # data source was resolved during this run
    source: SourceDoc = field(default_factory=SourceDoc)
    crs: Optional[CrsDoc] = None
    geometry_type: Optional[str] = None
    wkb_type: Optional[str] = None
    feature_count: Optional[int] = None
    extent: Optional[list] = None  # [xmin, ymin, xmax, ymax] in the layer CRS
    fields: list = field(default_factory=list)  # FieldDoc
    joins: list = field(default_factory=list)  # JoinDoc
    subset_string: Optional[str] = None
    scale_visibility: Optional[dict] = None  # {"min_scale": .., "max_scale": ..} when enabled
    opacity: Optional[float] = None
    blend_mode: Optional[str] = None
    title: Optional[str] = None
    abstract: Optional[str] = None
    keywords: dict = field(default_factory=dict)
    notes: Optional[str] = None  # plain text
    raster: Optional[dict] = None  # band_count, width, height, data_type, pixel_size
    style: Optional[dict] = None  # renderer, labeling, legend, qml, named_styles (collectors/styling.py)
    thumbnail: Optional[str] = None  # image of the layer alone (collectors/maps.py)


@dataclass
class TreeNode:
    kind: str  # "group" | "layer"
    name: str
    visible: bool = True
    expanded: bool = True
    layer_id: Optional[str] = None
    mutually_exclusive: bool = False
    embedded: bool = False
    children: list = field(default_factory=list)


@dataclass
class RelationDoc:
    id: str
    name: str
    referencing_layer_id: str = ""
    referencing_layer_name: Optional[str] = None
    referenced_layer_id: str = ""
    referenced_layer_name: Optional[str] = None
    field_pairs: list = field(default_factory=list)  # [{"referencing": .., "referenced": ..}]
    strength: str = ""
    valid: bool = False


@dataclass
class ThemeLayer:
    layer_id: str
    layer_name: Optional[str] = None
    style: Optional[str] = None  # named style, when the theme pins one


@dataclass
class ThemeDoc:
    name: str
    layers: list = field(default_factory=list)  # ThemeLayer, the layers visible in the theme


@dataclass
class BookmarkDoc:
    id: str
    name: str
    group: str = ""
    extent: Optional[list] = None
    crs: str = ""
    rotation: float = 0.0


@dataclass
class VariableDoc:
    name: str
    value: Any = None  # string or {"redacted": kind}


@dataclass
class ProjectDoc:
    title: str = ""
    file_name: str = ""
    file_path: str = ""
    qgis_version_saved: str = ""
    saved_at: Optional[str] = None
    crs: Optional[CrsDoc] = None
    ellipsoid: str = ""
    distance_units: str = ""
    area_units: str = ""
    path_storage: str = ""  # Relative | Absolute
    home_path: Optional[str] = None
    background_color: Optional[str] = None
    selection_color: Optional[str] = None
    default_view_extent: Optional[list] = None
    metadata: dict = field(default_factory=dict)
    has_macros: bool = False
    macro_lines: int = 0
    transform_operations: list = field(default_factory=list)  # [{"source", "destination", "operation"}]
    overview_image: Optional[str] = None  # visible layers at the full extent


@dataclass
class DocModel:
    schema: str = SCHEMA_ID
    generator: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)
    project: ProjectDoc = field(default_factory=ProjectDoc)
    layer_tree: Optional[TreeNode] = None
    layers: list = field(default_factory=list)  # LayerDoc, in layer-tree order
    relations: list = field(default_factory=list)
    themes: list = field(default_factory=list)
    bookmarks: list = field(default_factory=list)
    variables: list = field(default_factory=list)
    layouts: list = field(default_factory=list)  # print layouts and reports (collectors/layouts.py)
    resources: dict = field(default_factory=dict)  # fonts and external files (collectors/fonts_files.py)
    coverage: dict = field(default_factory=dict)  # share of project XML explained (collectors/tier_b.py)
    tier_b: list = field(default_factory=list)  # unexplained XML paths, detail == "full" only
    problems: list = field(default_factory=list)
    redactions: dict = field(default_factory=dict)  # kind -> total count

    def add_problem(self, severity, section, message, layer_id=None):
        self.problems.append(Problem(severity, section, message, layer_id))

    def count_redactions(self, kinds):
        for kind, n in dict(kinds).items():
            self.redactions[kind] = self.redactions.get(kind, 0) + n

    def layer(self, layer_id):
        return next((lyr for lyr in self.layers if lyr.id == layer_id), None)

    def to_dict(self):
        return asdict(self)

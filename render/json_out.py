# SPDX-License-Identifier: GPL-2.0-or-later
"""Machine output: the DocModel as schema-versioned JSON (docs/DESIGN.md section 8).

Two parts: `semantic` (structured, for tools that analyse a project) and `rebuild` (the
lossless payload: redacted project XML with parameterised sources and embedded SVG/images,
read by core/rebuild.py). JSON Schema: docs/schema/docqgisproject-1.schema.json.
"""

import json
import math
from dataclasses import asdict, is_dataclass


def _clean(value):
    """Recursively make a value strict-JSON safe (no NaN/inf, only JSON types)."""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"value of type {type(value).__name__} is not JSON-ready")


SEMANTIC_KEYS = (
    "project",
    "layer_tree",
    "layers",
    "relations",
    "themes",
    "bookmarks",
    "variables",
    "layouts",
    "resources",
)


def model_to_json_dict(model):
    """{schema, generator, options, semantic, rebuild, screenshots, problems, redactions, coverage, tier_b}."""
    data = _clean(model)
    return {
        "schema": data["schema"],
        "generator": data["generator"],
        "options": data["options"],
        "semantic": {k: data[k] for k in SEMANTIC_KEYS},
        "rebuild": data["rebuild"],
        "screenshots": data["screenshots"],
        "problems": data["problems"],
        "redactions": data["redactions"],
        "coverage": data["coverage"],
        "tier_b": data["tier_b"],
    }


def render_json(model):
    return json.dumps(model_to_json_dict(model), indent=2, ensure_ascii=False, allow_nan=False) + "\n"

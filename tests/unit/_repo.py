"""Shared helpers for the unit tests (pure Python, no QGIS)."""

import configparser
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def metadata():
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(ROOT / "metadata.txt", encoding="utf-8")
    return cp["general"]


def manifest():
    """Parse plugin_build.conf with the build script's own (non-executing) parser."""
    spec = importlib.util.spec_from_file_location("build_plugin", ROOT / "scripts" / "build_plugin.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.parse_manifest(ROOT / "plugin_build.conf")

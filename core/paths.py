# SPDX-License-Identifier: GPL-2.0-or-later
"""How paths are written in the documentation (option `paths`). Pure Python, unit-tested.

"relative" (default): relative to the project folder, as QGIS writes them ("./x.gpkg",
"../data/x.gpkg"). No home-folder path appears in any output, and the outputs stay valid when
the whole tree moves. A path on another Windows drive has no relative form and stays absolute.

"absolute": full paths everywhere, including the project file's own path.
"""

import ntpath
import os
import posixpath
import re

PATH_MODES = ("relative", "absolute")
# A URL scheme ("javascript:", "postgres:"), not a Windows drive ("C:"), is never a file path.
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")
_NOT_FILES = ("http://", "https://", "ftp://", "base64:", "data:", ":/", "/vsicurl", "/vsis3", "/vsigs", "/vsiaz")


class PathStyle:
    """show(path) converts one path. text(value) rewrites every absolute path inside free text
    (relative mode only) by replacing the project folder and up to MAX_UP of its parents with
    ".", "..", "../..". That replacement is exact for any path below those folders, so it is safe
    on XML and prose; the file-system root itself is never rewritten."""

    MAX_UP = 4

    def __init__(self, project_dir, mode="relative", pathmod=os.path):
        if mode not in PATH_MODES:
            raise ValueError(f"unknown path mode {mode!r}")
        self.mode = mode
        self.p = pathmod
        self.dir = self.p.normpath(self.p.abspath(project_dir)) if project_dir else None
        self._prefixes = []  # (folder, replacement), deepest folder first
        if self.dir and mode == "relative":
            folder, up = self.dir, 0
            while up <= self.MAX_UP:
                parent = self.p.dirname(folder)
                if parent == folder:  # reached the root
                    break
                self._prefixes.append((folder, "." if up == 0 else "/".join([".."] * up)))
                folder, up = parent, up + 1

    def absolute(self, path):
        if not path or not isinstance(path, str) or path.lower().startswith(_NOT_FILES) or _SCHEME_RE.match(path):
            return path
        if self.p.isabs(path) or not self.dir:
            return self.p.normpath(path)
        return self.p.normpath(self.p.join(self.dir, path))

    def show(self, path):
        if not path or not isinstance(path, str) or path.lower().startswith(_NOT_FILES) or _SCHEME_RE.match(path):
            return path
        full = self.absolute(path)
        if self.mode == "absolute" or not self.dir:
            return full
        try:
            rel = self.p.relpath(full, self.dir)
        except ValueError:  # another drive on Windows
            return full
        rel = rel.replace("\\", "/")
        return rel if rel.startswith("..") or rel == "." else "./" + rel

    def text(self, value):
        if self.mode != "relative" or not self._prefixes or not isinstance(value, str):
            return value
        if value in {f for f, _r in self._prefixes}:
            return dict(self._prefixes)[value]
        out = value
        seps = ("/", "\\") if self.p is ntpath else ("/",)
        for folder, repl in self._prefixes:  # deepest first, so a parent never splits a child
            for sep in seps:
                variant = folder.replace("\\", "/") if sep == "/" else folder
                out = out.replace(variant + sep, repl + "/")
                # The folder itself, ending at a path boundary ("see /a/b." or "/a/b" at the end).
                out = re.sub(re.escape(variant) + r"(?![\w.\\/-])", lambda _m, r=repl: r, out)
        return out


def restyle(obj, style, skip=("data_base64", "sha256"), depth=0):
    """Apply style.text to every string in a model (dataclasses, dicts, lists), in place where
    possible. Returns the new value."""
    if depth > 200 or style.mode != "relative":
        return obj
    if isinstance(obj, str):
        return style.text(obj)
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            obj[i] = restyle(v, style, skip, depth + 1)
        return obj
    if isinstance(obj, tuple):
        return tuple(restyle(v, style, skip, depth + 1) for v in obj)
    if isinstance(obj, dict):
        for k in list(obj):
            if k not in skip:
                obj[k] = restyle(obj[k], style, skip, depth + 1)
        return obj
    if hasattr(obj, "__dataclass_fields__"):
        for name in obj.__dataclass_fields__:
            if name not in skip:
                setattr(obj, name, restyle(getattr(obj, name), style, skip, depth + 1))
        return obj
    return obj


__all__ = ["PATH_MODES", "PathStyle", "restyle", "posixpath", "ntpath"]

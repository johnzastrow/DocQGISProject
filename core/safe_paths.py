# SPDX-License-Identifier: GPL-2.0-or-later
"""Output-folder handling: every file the plugin writes goes through OutputFolder.

Rules (docs/DESIGN.md section 9):
- files are written only inside the folder the user chose;
- names are validated against an allowlist (invalid names are rejected, not "fixed");
  sanitize_name() exists for deriving a name from project text (layer names) up front;
- symlinks are never followed or replaced;
- an existing file is overwritten only if this plugin wrote it before (recorded in a
  manifest in the folder) or the user chose "overwrite";
- writes are atomic (temporary file in the same folder, then os.replace);
- written files get normal user-file permissions (0o666 minus the process umask), the same
  as any file the user saves; mkstemp alone would leave them owner-only (0o600).
"""

import json
import os
import re
import tempfile
from pathlib import Path

MANIFEST_NAME = ".docqgisproject-manifest.json"
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


def _current_umask():
    """The process umask. Read from /proc on Linux (no side effects); otherwise set and restore."""
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("Umask:"):
                    return int(line.split()[1], 8)
    except (OSError, ValueError):
        pass
    old = os.umask(0o022)
    os.umask(old)
    return old


FILE_MODE = 0o666 & ~_current_umask()
_RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


class UnsafePathError(ValueError):
    """A requested output name is invalid or would leave the output folder."""


class OutputExistsError(FileExistsError):
    """The target exists, was not written by this plugin, and overwrite is off."""


def validate_name(name):
    """Validate a relative output name like 'report.md' or 'images/map_1.png'. Returns the parts."""
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name or name.startswith("/"):
        raise UnsafePathError(f"invalid output name: {name!r}")
    parts = name.split("/")
    for part in parts:
        if not _SEGMENT_RE.match(part) or part in (".", "..") or part.split(".")[0].lower() in _RESERVED:
            raise UnsafePathError(f"invalid output name: {name!r}")
    return parts


def sanitize_name(text, default="item", max_len=60):
    """Derive a safe single file-name segment from arbitrary project text (e.g. a layer name)."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "")).strip("._-")
    s = s[:max_len].rstrip("._-")
    if not s or s.split(".")[0].lower() in _RESERVED:
        s = default
    return s


class OutputFolder:
    """A user-chosen output folder that the plugin writes into safely."""

    def __init__(self, root, overwrite=False):
        root = Path(root)
        if root.is_symlink():
            raise UnsafePathError(f"output folder is a symbolic link: {root}")
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve(strict=True)
        self.overwrite = bool(overwrite)
        self._owned = self._load_manifest()
        self.written = []

    # -- manifest of files this plugin wrote ------------------------------------------
    def _load_manifest(self):
        path = self.root / MANIFEST_NAME
        if path.is_symlink() or not path.is_file():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {n for n in data.get("files", []) if isinstance(n, str)}
        except (OSError, ValueError):
            return set()  # unreadable manifest: own nothing (fail closed)

    def _save_manifest(self):
        names = sorted(self._owned)
        self._atomic_write(self.root / MANIFEST_NAME, json.dumps({"files": names}, indent=2).encode("utf-8"))

    # -- path checks ----------------------------------------------------------------
    def path_for(self, name):
        """Return the absolute target path for a validated name, after all safety checks."""
        parts = validate_name(name)
        target = self.root.joinpath(*parts)
        # Every existing component must be a real directory/file inside root (no symlinks).
        probe = self.root
        for part in parts:
            probe = probe / part
            if probe.is_symlink():
                raise UnsafePathError(f"refusing to write through a symbolic link: {name}")
        if os.path.commonpath([str(self.root), str(target.parent.resolve())]) != str(self.root):
            raise UnsafePathError(f"output name leaves the output folder: {name}")
        if target.exists() and name not in self._owned and not self.overwrite:
            raise OutputExistsError(
                f"{target} already exists and was not written by DocQGISProject; choose another folder or enable overwrite"
            )
        return target

    def check_writable(self, names):
        """Validate all names before writing anything (fail before partial output)."""
        for name in names:
            self.path_for(name)

    # -- writing --------------------------------------------------------------------
    @staticmethod
    def _atomic_write(target, data):
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.chmod(tmp, FILE_MODE)  # mkstemp creates 0o600; match a normally saved file
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def write_bytes(self, name, data):
        target = self.path_for(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(target, data)
        self._owned.add(name)
        self._save_manifest()
        self.written.append(str(target))
        return str(target)

    def write_text(self, name, text):
        return self.write_bytes(name, text.encode("utf-8"))

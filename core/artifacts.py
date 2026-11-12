# SPDX-License-Identifier: GPL-2.0-or-later
"""ArtifactSink: holds generated files (images, QML) in memory until the run succeeds.

Collectors add artifacts here; the runner writes them through OutputFolder only after every
collector finished, so a cancelled or failed run leaves the output folder untouched.
Budgets bound memory and disk use on huge projects (design section 9, denial of service).
"""

from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice

from .safe_paths import validate_name

DEFAULT_MAX_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_FILES = 5000


class BudgetExceeded(Exception):
    """The artifact budget is used up; the caller records a note and continues."""


class ArtifactSink:
    def __init__(self, images=True, max_bytes=DEFAULT_MAX_BYTES, max_files=DEFAULT_MAX_FILES):
        self.images = images
        self.max_bytes = max_bytes
        self.max_files = max_files
        self.files = {}  # name -> bytes, insertion ordered
        self.size = 0
        self.dropped = 0

    def _add(self, name, data):
        validate_name(name)
        if name in self.files:
            raise ValueError(f"duplicate artifact name: {name}")
        if len(self.files) >= self.max_files or self.size + len(data) > self.max_bytes:
            self.dropped += 1
            raise BudgetExceeded(name)
        self.files[name] = data
        self.size += len(data)
        return name

    def add_text(self, name, text):
        return self._add(name, text.encode("utf-8"))

    TEXT_SUFFIXES = (".qml", ".qpt", ".xml", ".txt", ".md", ".json", ".svg")

    def restyle_text(self, convert):
        """Apply convert(str) -> str to every text artifact (QML, QPT, ...). Used to make paths
        relative after collection. Sizes are recomputed; the budget is not re-checked (paths only
        get shorter or stay the same in practice)."""
        for name, data in list(self.files.items()):
            if not name.lower().endswith(self.TEXT_SUFFIXES):
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            new = convert(text)
            if new != text:
                encoded = new.encode("utf-8")
                self.size += len(encoded) - len(data)
                self.files[name] = encoded

    def add_png(self, name, image):
        """Encode a QImage as PNG. Returns the name, or None when images are off or it failed."""
        if not self.images or image is None or image.isNull():
            return None
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        ok = image.save(buf, "PNG")
        buf.close()
        if not ok:
            return None
        try:
            return self._add(name, bytes(data))
        except BudgetExceeded:
            return None

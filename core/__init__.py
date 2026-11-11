# SPDX-License-Identifier: GPL-2.0-or-later
"""UI-free documentation engine.

Rule (docs/DESIGN.md principle 5): nothing under core/ may import qgis.gui,
qgis.utils (iface) or Qt widget modules. tests/unit/test_core_isolation.py enforces it.
"""

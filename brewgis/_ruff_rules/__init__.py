"""Ruffian custom rules plugin — BrewGIS anti-pattern checks.

This package provides AST-based checkers for BrewGIS-specific anti-patterns
that Ruff's built-in rules do not cover.  It is consumed as a ruffian plugin
(see ``check.py``) and can also be run standalone.
"""

from __future__ import annotations

from brewgis._ruff_rules.rules import check_file

__all__ = ["check_file"]

#!/usr/bin/env python3
"""Pre-commit hook: ban @method_decorator on standalone functions.

``@method_decorator(..., name='dispatch')`` is only valid on class-based views.
Applied to a function-based view, it silently wraps incorrectly, causing a
TypeError at runtime.  This hook flags every ``@method_decorator`` that is
applied to a ``def`` (standalone function) rather than a ``class``.

Neither ruff nor mypy can catch this — the decorator type signature is too
generic.  This hook fills that gap.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def check_file(path: Path) -> list[str]:
    """Return list of error messages for any misuse in *path*."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    errors: list[str] = []

    for node in ast.iter_child_nodes(tree):
        # We only care about top-level decorated things.
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.decorator_list:
            continue

        has_method_decorator = any(
            _is_method_decorator_call(d) for d in node.decorator_list
        )
        if not has_method_decorator:
            continue

        # If the decorated node is a function (not a class), flag it.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            errors.append(
                f"{path}:{node.lineno}: "
                f"@method_decorator on function '{node.name}' — "
                f"use @user_passes_test / @login_required directly on FBVs"
            )

    return errors


def _is_method_decorator_call(node: ast.expr) -> bool:
    """Return True if *node* is a ``@method_decorator(...)`` call."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "method_decorator"
    )


def main() -> int:
    root = Path.cwd()
    files: list[Path] = []

    # If filenames passed on argv, use them; otherwise scan workspace/views.
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            p = Path(arg)
            if p.is_file():
                files.append(p)
    else:
        views_dir = root / "brewgis" / "workspace" / "views"
        if views_dir.is_dir():
            files.extend(views_dir.rglob("*.py"))
    # Also check any other file that imports method_decorator
    # (scan is cheaper than false negatives)
    default_scan_dirs = ["brewgis"]
    if not sys.argv[1:]:
        for d in default_scan_dirs:
            p = root / d
            if p.is_dir():
                for f in p.rglob("*.py"):
                    if f not in files:
                        files.append(f)

    errors: list[str] = []
    for f in sorted(files):
        errors.extend(check_file(f))

    for err in errors:
        print(err, file=sys.stderr)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

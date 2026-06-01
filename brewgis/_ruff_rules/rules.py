"""Pure AST-based rule checkers for BrewGIS anti-patterns.

Each rule function takes a source file path and returns a list of
ruff-compatible violation dicts.  No external dependencies beyond
the stdlib.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


# ── Helpers ──────────────────────────────────────────────────────


def _read_source(path: str | Path) -> tuple[str, ast.AST]:
    """Return (source_text, parsed_ast) for *path*."""
    text = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    return text, tree


def _is_dbt_or_migration(path: str | Path) -> bool:
    """Return True if *path* belongs to a dbt model or Django migration."""
    p = Path(path).as_posix()
    return "/migrations/" in p or "/dbt_project/" in p


# ── Violation builder ────────────────────────────────────────────


def _violation(
    code: str,
    message: str,
    path: str | Path,
    lineno: int,
    col: int = 0,
    end_lineno: int | None = None,
    end_col: int | None = None,
) -> dict[str, Any]:
    """Build a ruffian-compatible violation dict."""
    return {
        "code": code,
        "message": message,
        "filename": str(Path(path).resolve()),
        "location": {"row": lineno, "column": col},
        "end_location": {"row": end_lineno or lineno, "column": end_col or col},
        "url": None,
        "fix": None,
    }


# ══════════════════════════════════════════════════════════════════
#  Rule: brewgis/error-return-dict
# ══════════════════════════════════════════════════════════════════
#  Catches ``return {"success": False, ...}``,
#  ``return {"error": ...}``, ``return {"status": "error", ...}``
#  in function bodies.
# ══════════════════════════════════════════════════════════════════


def _is_error_dict(d: ast.Dict) -> bool:
    """Return True if *d* is a dict literal that signals an error return."""
    keys: list[str | None] = []
    for k in d.keys:
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.append(k.value)
        else:
            keys.append(None)

    # Check for "success": False
    for k, v in zip(keys, d.values):
        if k == "success" and _is_false(v):
            return True
        # "status": "error"
        if k == "status" and _is_str_literal(v, "error"):
            return True

    # Check for "error" key with a truthy value
    for k, v in zip(keys, d.values):
        if k == "error" and not _is_none(v):
            return True

    return False


def _is_false(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and node.value is False:
        return True
    if isinstance(node, ast.Name) and node.id == "False":
        return True
    return False


def _is_none(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.Name) and node.id == "None":
        return True
    return False


def _is_str_literal(node: ast.AST, val: str) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == val


def _find_error_return_dicts(source: str, tree: ast.AST, path: str | Path) -> list[dict[str, Any]]:
    """Scan for error-return-dict violations."""
    violations: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Return):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        if _is_error_dict(node.value):
            # Only flag returns inside function/asyncfunction bodies
            for parent in _ancestors(tree, node):
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    lineno = getattr(node, "lineno", 0)
                    end_lineno = getattr(node, "end_lineno", None)
                    violations.append(
                        _violation(
                            "brewgis/error-return-dict",
                            "Returning error dict from function instead of raising an exception. "
                            "Use `raise SomeError(...)` so callers get a stack trace pointing "
                            "to the exact failure site.",
                            path,
                            lineno,
                            end_lineno=end_lineno,
                        )
                    )
                    break

    return violations


def _ancestors(tree: ast.AST, target: ast.AST) -> list[ast.AST]:
    """Walk from *target* up through the AST root, returning ancestor nodes."""

    class Finder(ast.NodeVisitor):
        def __init__(self) -> None:
            self.path: list[ast.AST] = []
            self.result: list[ast.AST] = []

        def generic_visit(self, node: ast.AST) -> None:
            self.path.append(node)
            if node is target:
                self.result = list(self.path)
            super().generic_visit(node)
            self.path.pop()

    finder = Finder()
    finder.visit(tree)
    # Return all ancestors excluding the target itself
    return finder.result[:-1] if finder.result else []


# ══════════════════════════════════════════════════════════════════
#  Rule: brewgis/early-return-empty-data
# ══════════════════════════════════════════════════════════════════
#  Catches::
#
#    if not records:
#        return {"table_name": ..., "row_count": 0}
#
#  ── guard clause on empty data that returns a result dict with
#     zero/none count values instead of raising.
# ══════════════════════════════════════════════════════════════════

# Dict keys that suggest a data-result dictionary
_RESULT_KEYS: frozenset[str] = frozenset(
    {
        "row_count",
        "count",
        "table_name",
        "records",
        "data",
        "n",
        "rows",
    }
)


def _is_zero_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value == 0 or node.value == 0.0
    return False


def _has_result_key(d: ast.Dict) -> bool:
    """Return True if the dict literal has keys resembling a data result."""
    for k in d.keys:
        key_str: str | None = None
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            key_str = k.value
        if key_str and key_str in _RESULT_KEYS:
            return True
    return False


def _has_zero_value(d: ast.Dict) -> bool:
    """Return True if any dict value is a literal 0 or 0.0."""
    return any(_is_zero_literal(v) for v in d.values)


def _find_early_return_empty_data(
    source: str, tree: ast.AST, path: str | Path
) -> list[dict[str, Any]]:
    """Scan for early-return-empty-data violations."""
    violations: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue

        # Pattern: ``if not <name>:``
        if not (
            isinstance(node.test, ast.UnaryOp)
            and isinstance(node.test.op, ast.Not)
            and isinstance(node.test.operand, ast.Name)
        ):
            continue

        # Body must be a single Return with a Dict value
        # Last statement in body must be a Return with a Dict;
        # earlier statements (logging, etc.) are allowed.
        last_stmt = node.body[-1] if node.body else None
        if not isinstance(last_stmt, ast.Return):
            continue
        if not isinstance(last_stmt.value, ast.Dict):
            continue

        d: ast.Dict = last_stmt.value

        # Must have at least one zero value
        if not _has_zero_value(d):
            continue

        # Must have at least one result key
        if not _has_result_key(d):
            continue

        # Avoid flagging legitimate config returns (has non-result keys
        # like "enabled" but no data-result keys)
        # Actually the above check handles this — we already require
        # _has_result_key.

        lineno = getattr(node, "lineno", 0)
        end_lineno = getattr(node, "end_lineno", None)
        violations.append(
            _violation(
                "brewgis/early-return-empty-data",
                "Guard clause on empty data returns a result dict with zero count "
                "instead of raising. Empty data is an exceptional condition — "
                "use `raise RuntimeError(...)` so callers can't silently consume "
                "a zero-result.",
                path,
                lineno,
                end_lineno=end_lineno,
            )
        )

    return violations


# ══════════════════════════════════════════════════════════════════
#  Rule: brewgis/silent-exception-swallow
# ══════════════════════════════════════════════════════════════════
#  Catches ``except Exception:`` / ``except BaseException:`` / bare
#  ``except:`` where the handler only logs/warns/passes and does NOT
#  re-raise.  Logging without re-raise silences the failure.
# ══════════════════════════════════════════════════════════════════

_BARE_BROAD_NAMES: frozenset[str] = frozenset({"Exception", "BaseException"})


def _is_raise_or_reraise(node: ast.AST) -> bool:
    """Return True if *node* is a raise statement or a call that re-raises."""
    if isinstance(node, ast.Raise):
        return True
    return False


def _handler_only_logs(body: list[ast.AST]) -> bool:
    """Return True if every statement in *body* is just logging/pass."""
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr):
            call = stmt.value
            # logger.warning(...), logger.exception(...), etc.
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                if call.func.attr in {"warning", "error", "exception", "info", "debug", "log"}:
                    # Check if the callee has 'logger' in its name
                    if isinstance(call.func.value, ast.Name) and (
                        "log" in call.func.value.id.lower()
                    ):
                        continue
                    if isinstance(call.func.value, ast.Attribute) and (
                        "log" in call.func.value.attr.lower()
                    ):
                        continue
            # print(...)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                if call.func.id == "print":
                    continue
        if isinstance(stmt, ast.If):
            # Recursively check if blocks only log
            if not _handler_only_logs(stmt.body) or not _handler_only_logs(stmt.orelse):
                return False
            continue
        # Anything else is not "just logging"
        return False
    return True


def _find_silent_exception_swallows(
    source: str, tree: ast.AST, path: str | Path
) -> list[dict[str, Any]]:
    """Scan for silent-exception-swallow violations."""
    violations: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue

        for handler in node.handlers:
            # Catch bare except, except Exception, except BaseException
            if handler.type is None:
                is_broad = True
            elif isinstance(handler.type, ast.Name) and handler.type.id in _BARE_BROAD_NAMES:
                is_broad = True
            else:
                continue  # not a broad except

            # Check if handler has a re-raise anywhere
            has_raise = any(
                isinstance(stmt, ast.Raise) for stmt in ast.walk(ast.Module(body=handler.body, type_ignores=[]))
            )

            if has_raise:
                continue

            # Only flag if handler only logs (no other meaningful action)
            if not _handler_only_logs(handler.body):
                continue

            lineno = getattr(handler, "lineno", 0)
            type_name = "bare except" if handler.type is None else handler.type.id  # type: ignore[union-attr]
            violations.append(
                _violation(
                    "brewgis/silent-exception-swallow",
                    f"Silent `{type_name}` handler — logs warning but does not re-raise. "
                    "This masks upstream failures (e.g. missing staging tables → zero-filled data). "
                    "Either re-raise, let the exception propagate, or handle it explicitly.",
                    path,
                    lineno,
                    end_lineno=getattr(handler, "end_lineno", None),
                )
            )

    return violations


# ══════════════════════════════════════════════════════════════════
#  Rule: brewgis/python-sql-ddl
# ══════════════════════════════════════════════════════════════════
#  Catches ``CREATE TABLE`` / ``CREATE VIEW`` in SQL strings passed
#  to ``execute()`` or ``text()``.  Excludes dbt models and
#  migrations.
# ══════════════════════════════════════════════════════════════════

_DDL_RE = re.compile(r"\bCREATE\s+(TABLE|VIEW|MATERIALIZED\s+VIEW)\b", re.IGNORECASE)


def _find_sql_ddl(source: str, tree: ast.AST, path: str | Path) -> list[dict[str, Any]]:
    """Scan for python-sql-ddl violations."""
    if _is_dbt_or_migration(path):
        return []

    violations: list[dict[str, Any]] = []

    # Skip own module (documentation strings references pattern names)
    if "/_ruff_rules/" in Path(path).as_posix():
        return []

    def _check_string(s: str, lineno: int) -> None:
        if _DDL_RE.search(s):
            violations.append(
                _violation(
                    "brewgis/python-sql-ddl",
                    "SQL DDL (`CREATE TABLE`/`CREATE VIEW`) found in Python source. "
                    "Only three things are allowed to create models: "
                    "Django Migrations, dbt, and dlt. Use a dbt model instead.",
                    path,
                    lineno,
                )
            )

    for node in ast.walk(tree):
        # f"...CREATE TABLE..." → joined str / f-string
        if isinstance(node, ast.Call):
            func_name = _get_call_func_name(node)
            if func_name in ("execute", "text", "executescript"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        _check_string(arg.value, getattr(arg, "lineno", 0))
                    elif isinstance(arg, ast.JoinedStr):
                        for val in arg.values:
                            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                                _check_string(val.value, getattr(arg, "lineno", 0))

            for kw in getattr(node, "keywords", []):
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value, str):
                    _check_string(kw.value, getattr(kw.value, "lineno", 0))

    return violations


def _get_call_func_name(node: ast.Call) -> str:
    """Get the function name of a call as a dotted string."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


# ══════════════════════════════════════════════════════════════════
#  Rule: brewgis/no-direct-sqlalchemy
# ══════════════════════════════════════════════════════════════════
#  Catches ``import sqlalchemy`` / ``from sqlalchemy import`` outside
#  of ``_db.py``.
# ══════════════════════════════════════════════════════════════════

_SQLALCHEMY_MODULES: frozenset[str] = frozenset({
    "sqlalchemy",
    "geoalchemy2",
})


def _find_direct_sqlalchemy_imports(
    source: str, tree: ast.AST, path: str | Path
) -> list[dict[str, Any]]:
    """Scan for no-direct-sqlalchemy violations."""
    violations: list[dict[str, Any]] = []

    p = Path(path)
    if p.name == "_db.py":
        return []  # The one allowed file

    # Only enforce within workspace app (matches architecture test scope)
    if "/brewgis/workspace/" not in p.as_posix():
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name.split(".")[0]
                if module in _SQLALCHEMY_MODULES:
                    # Check if directly sqlalchemy, not sqlalchemy.orm which is ok
                    # Actually _db.py is the only allowed file for any sqlalchemy import
                    violations.append(
                        _violation(
                            "brewgis/no-direct-sqlalchemy",
                            f"Direct `import {alias.name}` found outside `_db.py`. "
                            f"All SQLAlchemy imports must go through "
                            f"`brewgis.workspace.services._db`.",
                            path,
                            getattr(node, "lineno", 0),
                        )
                    )
                    break

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module = node.module.split(".")[0]
                if module in _SQLALCHEMY_MODULES:
                    violations.append(
                        _violation(
                            "brewgis/no-direct-sqlalchemy",
                            f"Direct `from {node.module} import` found outside `_db.py`. "
                            f"All SQLAlchemy imports must go through "
                            f"`brewgis.workspace.services._db`.",
                            path,
                            getattr(node, "lineno", 0),
                        )
                    )

    return violations
    return violations


# ══════════════════════════════════════════════════════════════════
#  Rule: brewgis/dagster-import-scope
# ══════════════════════════════════════════════════════════════════
#  ``dagster`` must only be imported from within the dagster package
#  (``workspace/dagster/``) or ``workspace/analysis/pipeline.py``.
# ══════════════════════════════════════════════════════════════════

_DAGSTER_ALLOWED_PREFIXES: frozenset[str] = frozenset({
    "dagster/",
})
_DAGSTER_ALLOWED_FILES: frozenset[str] = frozenset({
    "pipeline.py",
})


def _find_dagster_import_scope(
    source: str, tree: ast.AST, path: str | Path
) -> list[dict[str, Any]]:
    """Scan for dagster-import-scope violations."""
    return _find_restricted_import(
        ["dagster"],
        "brewgis/dagster-import-scope",
        "`dagster` may only be imported from `workspace/dagster/` or `workspace/analysis/pipeline.py`.",
        _DAGSTER_ALLOWED_PREFIXES,
        _DAGSTER_ALLOWED_FILES,
        path,
        source, tree,
    )


# ══════════════════════════════════════════════════════════════════
#  Rule: brewgis/dagster-embedded-elt-scope
# ══════════════════════════════════════════════════════════════════
#  ``dagster_embedded_elt`` must only be imported from the dagster
#  package (``workspace/dagster/``).
# ══════════════════════════════════════════════════════════════════


def _find_dagster_embedded_elt_scope(
    source: str, tree: ast.AST, path: str | Path
) -> list[dict[str, Any]]:
    """Scan for dagster-embedded-elt-scope violations."""
    return _find_restricted_import(
        ["dagster_embedded_elt"],
        "brewgis/dagster-embedded-elt-scope",
        "`dagster_embedded_elt` may only be imported from `workspace/dagster/`.",
        _DAGSTER_ALLOWED_PREFIXES,
        frozenset(),
        path,
        source, tree,
    )


def _find_restricted_import(
    module_names: list[str],
    code: str,
    message: str,
    allowed_dir_prefixes: frozenset[str],
    allowed_files: frozenset[str],
    path: str | Path,
    source: str, tree: ast.AST,
) -> list[dict[str, Any]]:
    """Generic restricted-import checker."""
    p = Path(path)
    posix = p.as_posix()

    # Only enforce within workspace app
    if "/brewgis/workspace/" not in posix:
        return []

    # Check if this file is in an allowed directory
    for prefix in allowed_dir_prefixes:
        # Check relative path from workspace/
        workspace_idx = posix.find("/brewgis/workspace/")
        if workspace_idx != -1:
            rel = posix[workspace_idx + len("/brewgis/workspace/"):]
            if rel.startswith(prefix):
                return []

    # Check if this file is in the allowed files list
    if p.name in allowed_files:
        return []

    violations: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for mod in module_names:
                    if alias.name == mod or alias.name.startswith(mod + "."):
                        violations.append(
                            _violation(
                                code,
                                message,
                                path,
                                getattr(node, "lineno", 0),
                            )
                        )
                        break
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                for mod in module_names:
                    if node.module == mod or node.module.startswith(mod + "."):
                        violations.append(
                            _violation(
                                code,
                                message,
                                path,
                                getattr(node, "lineno", 0),
                            )
                        )
                        break
    return violations


# ══════════════════════════════════════════════════════════════════
#  Rule: brewgis/no-dlt-pipeline-outside-pipelines
# ══════════════════════════════════════════════════════════════════
#  ``dlt.pipeline(`` calls must only appear in ``dlt_pipelines/`` or
#  ``dagster/assets/``.
# ══════════════════════════════════════════════════════════════════

_DLT_ALLOWED_DIRS: frozenset[str] = frozenset({
    "dlt_pipelines",
    "dagster/assets",
})


def _find_dlt_pipeline_scope(
    source: str, tree: ast.AST, path: str | Path
) -> list[dict[str, Any]]:
    """Scan for no-dlt-pipeline-outside-pipelines violations."""
    p = Path(path)
    posix = p.as_posix()

    # Only enforce within workspace app
    if "/brewgis/workspace/" not in posix:
        return []

    # Check if this file is in an allowed directory
    workspace_idx = posix.find("/brewgis/workspace/")
    if workspace_idx != -1:
        rel = posix[workspace_idx + len("/brewgis/workspace/"):]
        if any(rel.startswith(d) for d in _DLT_ALLOWED_DIRS):
            return []

    # Check for dlt.pipeline( calls
    violations: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = _get_call_func_name(node)
            if func == "pipeline":
                # Must be called as dlt.pipeline(...)
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "dlt":
                        violations.append(
                            _violation(
                                "brewgis/no-dlt-pipeline-outside-pipelines",
                                "`dlt.pipeline()` call found outside allowed directories "
                                f"{_DLT_ALLOWED_DIRS}. Move this to `dlt_pipelines/` or `dagster/assets/`.",
                                path,
                                getattr(node, "lineno", 0),
                            )
                        )
    return violations


# ══════════════════════════════════════════════════════════════════
#  Rule: brewgis/no-try-in-soda
# ══════════════════════════════════════════════════════════════════
#  No ``try`` statements in validation/linting code (``brewgis/soda/``).
#  Exception handling masks upstream misconfiguration.
# ══════════════════════════════════════════════════════════════════


def _find_no_try_in_soda(
    source: str, tree: ast.AST, path: str | Path
) -> list[dict[str, Any]]:
    """Scan for no-try-in-soda violations."""
    p = Path(path)
    posix = p.as_posix()

    # Only enforce within brewgis/soda/
    if "/brewgis/soda/" not in posix:
        return []

    violations: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            violations.append(
                _violation(
                    "brewgis/no-try-in-soda",
                    "Exception handling found in soda validation code. "
                    "In validation/linting code, an exception means the target is "
                    "misconfigured — let the exception propagate instead of catching it.",
                    path,
                    getattr(node, "lineno", 0),
                )
            )
    return violations


# ══════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════


def check_file(path: str | Path) -> list[dict[str, Any]]:
    """Run all rules against a single file.

    Returns a list of violation dicts (empty list = no violations).
    """
    path = Path(path)
    if not path.suffix == ".py":
        return []
    if not path.exists():
        return []

    source, tree = _read_source(path)

    violations: list[dict[str, Any]] = []

    rules = [
        _find_error_return_dicts,
        _find_early_return_empty_data,
        _find_silent_exception_swallows,
        _find_sql_ddl,
        _find_direct_sqlalchemy_imports,
        _find_dagster_import_scope,
        _find_dagster_embedded_elt_scope,
        _find_dlt_pipeline_scope,
        _find_no_try_in_soda,
    ]

    for rule in rules:
        violations.extend(rule(source, tree, path))

    return violations

"""Architecture guard rules — import-level constraints enforced via pytestarch.

These rules prevent regression to the pre-centralized-DB-connection pattern
where every module built its own ``create_engine`` call from ``settings.DATABASES``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pytestarch import EvaluableArchitecture
from pytestarch import Rule
from pytestarch import get_evaluable_architecture

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def workspace_architecture() -> EvaluableArchitecture:
    """Scan only the workspace app — the module we own and enforce rules on."""
    workspace_dir = REPO_ROOT / "brewgis" / "workspace"
    return get_evaluable_architecture(
        str(workspace_dir),
        str(workspace_dir),
        exclude_external_libraries=False,
    )


@pytest.fixture(scope="session")
def tests_architecture() -> EvaluableArchitecture:
    """Scan only the tests directory."""
    return get_evaluable_architecture(
        str(REPO_ROOT),
        str(REPO_ROOT / "tests"),
        exclude_external_libraries=False,
    )


# ──────────────────────────────────────────────────────────────
#  Rule A — Single entry point for SQLAlchemy
# ──────────────────────────────────────────────────────────────
#  Only brewgis.workspace.services._db may import from sqlalchemy
#  directly. All other modules under brewgis.workspace must obtain
#  engines/text via _db.
# ──────────────────────────────────────────────────────────────

RULE_A_SINGLE_ENTRY_POINT = (
    Rule()
    .modules_that()
    .are_named("sqlalchemy")
    .should_only()
    .be_imported_by_modules_that()
    .are_named("workspace.services._db")
)


def test_sqlalchemy_only_imported_by_db(
    workspace_architecture: EvaluableArchitecture,
) -> None:
    """Verify only _db.py within workspace imports from sqlalchemy."""
    RULE_A_SINGLE_ENTRY_POINT.assert_applies(workspace_architecture)


# ──────────────────────────────────────────────────────────────
#  Rule B — No direct SQLAlchemy imports from tests
# ──────────────────────────────────────────────────────────────
#  Test files that need SQLAlchemy must go through _db.py.
# ──────────────────────────────────────────────────────────────


def test_no_direct_sqlalchemy_in_tests(
    tests_architecture: EvaluableArchitecture,
) -> None:
    """Verify no test file imports from sqlalchemy directly.

    Uses a direct graph check because pytestarch's ``are_named("sqlalchemy")``
    requires the target module to exist as a graph node, but ``sqlalchemy``
    will be absent when no test imports it (which is the desired state).
    """
    graph = tests_architecture._graph._graph
    violations = []
    for node in graph.nodes():
        if str(node).startswith("tests"):
            for dep in graph.successors(node):
                if "sqlalchemy" in str(dep):
                    violations.append(f"{node} imports {dep}")
    assert not violations, "\n".join(violations)


# ──────────────────────────────────────────────────────────────
#  Rule C — Dagster imports only within the dagster package
# ──────────────────────────────────────────────────────────────
#  dagster must only be imported from brewgis.workspace.dagster
#  (and its submodules). All other workspace modules must not
#  couple to Dagster directly.
# ──────────────────────────────────────────────────────────────


def test_dagster_only_imported_by_dagster_package(
    workspace_architecture: EvaluableArchitecture,
) -> None:
    """Verify dagster is only imported from within the dagster package.

    The external ``dagster`` package (not the local package) must only be
    imported by modules under ``workspace.dagster.*`` or the top-level
    dagster package itself, or by ``workspace.analysis.pipeline``
    which needs ``dagster_instance`` for launching runs.
    """
    allowed_prefixes = ("workspace.dagster", "workspace.analysis.pipeline")
    graph = workspace_architecture._graph._graph
    violations: list[str] = []
    for node in graph.nodes():
        node_str = str(node)
        # Imports of dagster-embedded-elt are handled separately
        if node_str.startswith(allowed_prefixes):
            continue
        for dep in graph.successors(node):
            dep_str = str(dep)
            # Only flag imports of the external "dagster" package itself
            if dep_str == "dagster":
                violations.append(f"{node_str} imports {dep_str}")
    assert not violations, "\n".join(violations)


def test_dagster_embedded_elt_only_in_dagster(
    workspace_architecture: EvaluableArchitecture,
) -> None:
    """Verify dagster_embedded_elt is only imported from the dagster package."""
    dagster_pkg_prefix = "workspace.dagster"
    graph = workspace_architecture._graph._graph
    violations: list[str] = []
    for node in graph.nodes():
        node_str = str(node)
        if node_str.startswith(dagster_pkg_prefix):
            continue
        # Skip dagster_embedded_elt's own internal submodule resolution
        if "dagster_embedded_elt" in node_str:
            continue
        for dep in graph.successors(node):
            dep_str = str(dep)
            if "dagster_embedded_elt" in dep_str:
                violations.append(f"{node_str} imports {dep_str}")
    assert not violations, "\n".join(violations)


def test_dlt_pipeline_only_in_pipelines_and_dagster() -> None:
    """Verify dlt.pipeline( calls are limited to dlt_pipelines/ and dagster/.

    Direct file scan since dlt.pipeline is a function call, not a
    module-level import.
    """
    allowed_dirs = {"dlt_pipelines", "dagster/assets"}
    violations: list[str] = []
    repo_root = Path(__file__).resolve().parent.parent
    workspace_dir = repo_root / "brewgis" / "workspace"
    for pyfile in workspace_dir.rglob("*.py"):
        if "__pycache__" in pyfile.parts:
            continue
        relative = pyfile.relative_to(workspace_dir)
        if any(str(relative).startswith(d) for d in allowed_dirs):
            continue
        content = pyfile.read_text(encoding="utf-8")
        if "dlt.pipeline(" in content:
            violations.append(str(relative))
    assert not violations, (
        f"dlt.pipeline( calls found outside allowed dirs {allowed_dirs}:\n"
        + "\n".join(violations)
    )


# ══════════════════════════════════════════════════════════════
#  Rule D — No silent exception-to-empty-data pattern
# ══════════════════════════════════════════════════════════════
#  Catching ``Exception`` / ``BaseException`` (or bare except)
#  and then returning an empty default (``GeoDataFrame()``,
#  ``DataFrame()``, ``[]``, ``{}``) silently masks upstream
#  failures — e.g. missing staging tables → zero-filled data.
#  The handler must at minimum ``raise`` or re-raise, or the
#  caller must explicitly handle the empty result.
# ══════════════════════════════════════════════════════════════

_SOURCE_DIRS_TO_SCAN = [
    REPO_ROOT / "brewgis" / "workspace" / "services",
    REPO_ROOT / "brewgis" / "workspace" / "management",
    REPO_ROOT / "brewgis" / "workspace" / "analysis",
    REPO_ROOT / "brewgis" / "gx",
]

# Common "empty default" constructors that signal data loss.
_EMPTY_RETURN_PATTERNS: tuple[tuple[str, ...], ...] = (
    # gpd.GeoDataFrame() / pd.DataFrame()
    ("GeoDataFrame",),
    ("DataFrame",),
    # gpd.GeoDataFrame([]) / pd.DataFrame([])
    ("GeoDataFrame", "list"),  # arg is []
    # [], {}
    ("list_empty",),
    ("dict_empty",),
)


def _is_empty_value(node: ast.AST) -> bool:
    """Return True if *node* is an empty-container expression such as
    ``GeoDataFrame()``, ``DataFrame()``, ``[]``, or ``{}``.
    ``None`` is excluded — it is a legitimate sentinel for
    "no result / couldn't compute", not a data-loss signal.
    """
    if isinstance(node, ast.List) and len(node.elts) == 0:
        return True
    if isinstance(node, ast.Dict) and len(node.keys) == 0:
        return True
    if isinstance(node, ast.Call):
        func = node.func
        # GeoDataFrame() or DataFrame() — possibly qualified (gpd.GeoDataFrame)
        if isinstance(func, ast.Name) and func.id in ("GeoDataFrame", "DataFrame"):
            return len(node.args) == 0 and len(node.keywords) == 0
        if isinstance(func, ast.Attribute) and func.attr in (
            "GeoDataFrame",
            "DataFrame",
        ):
            return len(node.args) == 0 and len(node.keywords) == 0
    return False


def _is_bare_or_broad_except(handler: ast.ExceptHandler) -> bool:
    """Return True if the except handler catches ``Exception``,
    ``BaseException``, or bare ``except:``."""
    if handler.type is None:
        return True  # bare except:
    if isinstance(handler.type, ast.Name) and handler.type.id in (
        "Exception",
        "BaseException",
    ):
        return True
    # Handle `except Exception as e:`
    if isinstance(handler.type, ast.Attribute) and handler.type.attr in (
        "Exception",
        "BaseException",
    ):
        return True
    return False


def _find_silent_exception_violations(filepath: Path) -> list[str]:
    """Scan a single file for the silent-exception-to-empty-data pattern.

    Returns human-readable violation descriptions.
    """
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"), filename=str(filepath))
    except SyntaxError:
        return []

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if not _is_bare_or_broad_except(handler):
                continue
            body = handler.body
            if not body:
                continue
            last_stmt = body[-1]
            if isinstance(last_stmt, ast.Raise):
                continue  # re-raise is fine
            if isinstance(last_stmt, ast.Return) and _is_empty_value(last_stmt.value):
                # Find a human-readable location
                line = last_stmt.lineno
                # Try to find the except clause line for a better message
                except_line = handler.lineno if hasattr(handler, "lineno") else line
                violations.append(
                    f"{filepath.relative_to(REPO_ROOT)}:{except_line}: "
                    f"except handler at line {handler.lineno} catches "
                    f"{'bare' if handler.type is None else ast.dump(handler.type)} "
                    f"and returns empty value at line {line}"
                )
    return violations


def test_no_silent_exception_returning_empty_data() -> None:
    """Verify no ``except Exception:``/``except BaseException:``/bare ``except:``
    handler returns an empty default (``GeoDataFrame()``, ``DataFrame()``, ``[]``,
    ``{}``, or ``None``).

    This pattern silently masks upstream failures such as missing staging
    tables.  Handlers that need to recover should log *and* re-raise, or
    return a sentinel the caller explicitly handles.
    """
    violations: list[str] = []
    for source_dir in _SOURCE_DIRS_TO_SCAN:
        if not source_dir.exists():
            continue
        for pyfile in source_dir.rglob("*.py"):
            if "__pycache__" in pyfile.parts:
                continue
            violations.extend(_find_silent_exception_violations(pyfile))
    assert not violations, (
        "Silent exception-to-empty-data pattern found (catch Exception/BaseException"
        " and return empty default without re-raising):\n" + "\n".join(violations)
    )


# ══════════════════════════════════════════════════════════════
#  Rule E — FileDataContext() must be guarded by existence check
# ══════════════════════════════════════════════════════════════
#  ``gx.data_context.FileDataContext(path)`` fails at runtime
#  when the target directory does not contain a valid GX config.
#  The caller must check ``path.exists()`` first.
# ══════════════════════════════════════════════════════════════


def test_file_data_context_guarded_by_exists() -> None:
    """Verify every ``FileDataContext(str(...))`` call is preceded by an
    ``.exists()`` call on the same path variable within the enclosing
    function.

    This catches the case where the Great Expectations config directory
    is missing, which otherwise produces a cryptic ``ConfigNotFoundError``
    at runtime.
    """
    target_prefixes = {
        # Relative path from REPO_ROOT
        "brewgis/gx",
        "brewgis/workspace",
    }
    violations: list[str] = []
    found_any = False
    for prefix in target_prefixes:
        scan_dir = REPO_ROOT / prefix
        if not scan_dir.exists():
            continue
        for pyfile in scan_dir.rglob("*.py"):
            if "__pycache__" in pyfile.parts:
                continue
            try:
                tree = ast.parse(
                    pyfile.read_text(encoding="utf-8"), filename=str(pyfile)
                )
            except SyntaxError:
                continue

            # Collect all FileDataContext calls in the file, with the
            # argument expression (which is usually str(some_var)).
            class FileDataContextVisitor(ast.NodeVisitor):
                def __init__(self) -> None:
                    self.calls: list[tuple[int, str | None]] = []  # (lineno, arg_repr)

                def visit_Call(self, node: ast.Call) -> None:
                    func = node.func
                    # Match gx.data_context.FileDataContext(...)
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "FileDataContext"
                        and isinstance(func.value, ast.Attribute)
                        and func.value.attr == "data_context"
                        and isinstance(func.value.value, ast.Name)
                        and func.value.value.id == "gx"
                    ):
                        arg_repr = None
                        if node.args:
                            arg_repr = (
                                ast.unparse(node.args[0])
                                if hasattr(ast, "unparse")
                                else str(node.args[0])
                            )
                        self.calls.append((node.lineno, arg_repr))
                    self.generic_visit(node)

            visitor = FileDataContextVisitor()
            visitor.visit(tree)
            if not visitor.calls:
                found_any = True
                continue  # no FileDataContext calls in this file, fine

            # For each function/class scope that contains a FileDataContext call,
            # check whether any statement in that scope calls .exists() on the
            # same variable before the FileDataContext call.
            for lineno, arg_repr in visitor.calls:
                # Find the enclosing function
                enclosing_function = None
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if node.lineno <= lineno <= node.end_lineno:
                            enclosing_function = node
                            break

                if enclosing_function is None:
                    violations.append(
                        f"{pyfile.relative_to(REPO_ROOT)}:{lineno}: "
                        f"FileDataContext call outside a function — "
                        f"cannot verify existence guard. arg={arg_repr}"
                    )
                    continue

                # Extract the base variable from the argument.
                # Typically str(project_dir) or str(project_dir / "gx").
                # We want to find "project_dir" as the base name.
                base_name = _extract_base_name(arg_repr) if arg_repr else None
                if base_name is None:
                    violations.append(
                        f"{pyfile.relative_to(REPO_ROOT)}:{lineno}: "
                        f"FileDataContext argument is not a simple variable "
                        f"reference — cannot verify existence guard. "
                        f"arg={arg_repr}"
                    )
                    continue

                # Walk the enclosing function's body for an .exists() call
                # on the base variable, occurring before the FileDataContext call.
                has_exists_guard = _has_exists_call_before(
                    enclosing_function, base_name, lineno
                )
                if not has_exists_guard:
                    violations.append(
                        f"{pyfile.relative_to(REPO_ROOT)}:{lineno}: "
                        f"FileDataContext(str({base_name})) at line {lineno} "
                        f"without {base_name}.exists() guard in "
                        f"function '{enclosing_function.name}'"
                    )

    # If we never found a single .py file with or without FileDataContext,
    # something is wrong with the scan.
    if not found_any and not violations:
        violations.append("No Python files scanned — check _SOURCE_DIRS_TO_SCAN paths")

    assert not violations, (
        "FileDataContext() calls must be guarded by a path.exists() check:\n"
        + "\n".join(violations)
    )


def _extract_base_name(arg_repr: str) -> str | None:
    """Extract the base variable name from a ``str(...)`` or path construction.

    ``str(project_dir)`` → ``project_dir``
    ``str(project_dir / "gx")`` → ``project_dir``
    ``project_dir`` → ``project_dir``
    """
    arg_repr = arg_repr.strip()
    # Handle str(...) wrapping
    if arg_repr.startswith("str(") and arg_repr.endswith(")"):
        inner = arg_repr[4:-1]
        return _extract_base_name(inner)
    # Handle base_dir / "subdir" — take the leftmost part
    if "/" in arg_repr or "//" in arg_repr:
        parts = arg_repr.replace("//", "/").split("/")
        base = parts[0].strip()
        # Might still be an expression like project_dir / "gx"
        # where the base is a Name
        return base.split()[0] if " " in base else base
    # Plain name
    return arg_repr if arg_repr.isidentifier() else None


def _has_exists_call_before(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    base_name: str,
    before_line: int,
) -> bool:
    """Check if the function body verifies that *base_name* exists (or a
    path derived from it) before *before_line*.

    Acceptable patterns:
        project_dir.exists()
        gx_config.exists()          # where gx_config = project_dir / ...
        Path(project_dir).exists()
    """
    # Collect variables assigned from base_name / ... or Path(base_name) ...
    derived_vars: set[str] = set()
    for stmt in ast.walk(func_node):
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                target_name = stmt.targets[0].id
                rhs = stmt.value
                # base_name / "something" → target_name is derived
                if (
                    isinstance(rhs, ast.BinOp)
                    and isinstance(rhs.left, ast.Name)
                    and rhs.left.id == base_name
                ):
                    derived_vars.add(target_name)
                # Path(base_name) → target_name is derived
                if (
                    isinstance(rhs, ast.Call)
                    and isinstance(rhs.func, ast.Name)
                    and rhs.func.id == "Path"
                    and rhs.args
                    and isinstance(rhs.args[0], ast.Name)
                    and rhs.args[0].id == base_name
                ):
                    derived_vars.add(target_name)

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "exists":
            obj = func.value
            # project_dir.exists()
            if isinstance(obj, ast.Name) and (
                obj.id == base_name or obj.id in derived_vars
            ):
                if hasattr(node, "lineno") and node.lineno < before_line:
                    return True
            # Path(project_dir).exists()
            if (
                isinstance(obj, ast.Call)
                and isinstance(obj.func, ast.Name)
                and obj.func.id == "Path"
                and obj.args
                and isinstance(obj.args[0], ast.Name)
                and obj.args[0].id == base_name
            ):
                if hasattr(node, "lineno") and node.lineno < before_line:
                    return True
            # (project_dir / "gx").exists() — BinOp with left = base_name
            if (
                isinstance(obj, ast.BinOp)
                and isinstance(obj.left, ast.Name)
                and obj.left.id == base_name
            ):
                if hasattr(node, "lineno") and node.lineno < before_line:
                    return True
    return False


# ══════════════════════════════════════════════════════════════
#  Rule F — No exception handling in validation/linting code
# ══════════════════════════════════════════════════════════════
#  In validation and linting routines (brewgis/soda/) an
#  exception means the target is misconfigured — missing
#  table, missing column, wrong schema.  Catching it and
#  returning a success would silently mask the failure.
#  The exception **must** propagate.
# ══════════════════════════════════════════════════════════════

_SODA_DIR = REPO_ROOT / "brewgis" / "soda"


def _find_try_nodes(filepath: Path) -> list[int]:
    """Return line numbers of every ``try`` statement in *filepath*."""
    tree = ast.parse(filepath.read_text(encoding="utf-8"))
    return [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Try)]


def test_no_exception_handling_in_soda() -> None:
    """Verify ``brewgis/soda/`` has zero ``try`` statements.

    Exception handling in validation/linting code would
    silently mask upstream misconfiguration (missing tables,
    wrong columns, etc.) as successful passes.
    """
    if not _SODA_DIR.exists():
        return

    violations: dict[str, list[int]] = {}
    for pyfile in _SODA_DIR.rglob("*.py"):
        if "__pycache__" in pyfile.parts:
            continue
        lines = _find_try_nodes(pyfile)
        if lines:
            violations[str(pyfile.relative_to(REPO_ROOT))] = lines

    assert not violations, (
        "Exception handling found in validation/linting code (try/except masks"
        " misconfiguration — let the exception propagate):\n"
        + "\n".join(
            f"  {path}:{','.join(str(ln) for ln in lines)}"
            for path, lines in violations.items()
        )
    )

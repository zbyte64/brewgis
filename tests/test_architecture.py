"""Architecture guard rules — import-level constraints enforced via pytestarch.
Rules that remain here are impractical for AST-only detection:
complex cross-function analysis (FileDataContext guard) or tests-directory
scope not covered by the linter (``ruffian check brewgis/``).
All other rules have been migrated to ``brewgis/_ruff_rules/rules.py``
and fire inline via LSP diagnostics on every edit.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pytestarch import EvaluableArchitecture
from pytestarch import get_evaluable_architecture

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def tests_architecture() -> EvaluableArchitecture:
    """Scan only the tests directory."""
    return get_evaluable_architecture(
        str(REPO_ROOT),
        str(REPO_ROOT / "tests"),
        exclude_external_libraries=False,
    )


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
        violations.append("No Python files scanned — check target_prefixes in test")

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

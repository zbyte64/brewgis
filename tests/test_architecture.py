"""Architecture guard rules — import-level constraints enforced via pytestarch.

These rules prevent regression to the pre-centralized-DB-connection pattern
where every module built its own ``create_engine`` call from ``settings.DATABASES``.
"""

from __future__ import annotations

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
        if any(
            str(relative).startswith(d)
            for d in allowed_dirs
        ):
            continue
        content = pyfile.read_text(encoding="utf-8")
        if "dlt.pipeline(" in content:
            violations.append(str(relative))
    assert not violations, (
        f"dlt.pipeline( calls found outside allowed dirs {allowed_dirs}:\n"
        + "\n".join(violations)
    )
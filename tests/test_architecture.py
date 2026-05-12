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

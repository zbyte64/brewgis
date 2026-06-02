"""pytest fixtures for orchestration-level isolation BDD tests.

These tests verify that the analysis pipeline (run_analysis_pipeline)
correctly creates AnalysisRun records with the right workspace,
scenario_id, and module isolation — without running real dbt.

run_modules_sync is patched with a MagicMock so pipeline dispatch
completes without executing SQLMesh.  Assertions check AnalysisRun
records and their properties rather than PostGIS views or schemas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from tests.factories import WorkspaceFactory

if TYPE_CHECKING:
    from collections.abc import Generator
    from typing import Any

    from brewgis.workspace.models import Workspace


# ── Module-level mark ────────────────────────────────────────────────────
# These tests need Django DB but NOT PostGIS/extensions — they only create
# Django-managed model records (Workspace, AnalysisRun).
pytestmark = [
    pytest.mark.django_db,
    pytest.mark.models,
]


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def scenario_context() -> dict[str, Any]:
    """Shared mutable dict for passing state between BDD steps.

    Follows the same pattern as tests/features/conftest.py.
    """
    return {}


@pytest.fixture
def mock_module_tasks() -> Generator[MagicMock, None, None]:  # type: ignore[misc]
    """Patch run_modules_sync so pipeline dispatch completes without running SQLMesh.

    When Dagster is unavailable (as in tests), run_analysis_pipeline falls
    back to run_modules_sync().  This fixture replaces it with a MagicMock
    so no real SQLMesh is executed.
    """
    with patch(
        "brewgis.workspace.analysis.pipeline.run_modules_sync",
    ) as mock_sync:
        mock_sync.return_value = {
            "success": True,
            "completed": [],
            "results": [],
        }
        yield mock_sync


@pytest.fixture
def default_workspace() -> Workspace:
    """Default workspace with ``db_schema="public"``, matching the BDD Background."""
    return WorkspaceFactory(db_schema="public", name="BDD Default Workspace")

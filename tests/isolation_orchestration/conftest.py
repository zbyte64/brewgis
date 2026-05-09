"""pytest fixtures for orchestration-level isolation BDD tests.

These tests verify that the analysis pipeline (run_analysis_pipeline +
_dispatch_next) correctly creates AnalysisRun records with the right
workspace, scenario_id, and module isolation — without running real dbt.

MODULE_TASKS are patched with MagicMocks so Celery dispatch is a no-op.
Assertions check AnalysisRun records and their properties rather than
PostGIS views or schemas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from brewgis.workspace.analysis.module_registry import MODULE_DEPENDENCIES
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
def mock_module_tasks() -> Generator[dict[str, MagicMock], None, None]:
    """Replace all MODULE_TASKS with MagicMocks for the duration of a test.

    Each mock provides ``apply_async`` so ``_dispatch_next`` succeeds
    without a Celery broker. Real dbt runs are NOT executed — the analysis
    pipeline creates the AnalysisRun record synchronously and attempts
    async dispatch, which this fixture absorbs.
    """
    mock_tasks = {m: MagicMock() for m in MODULE_DEPENDENCIES}
    with patch.dict(
        "brewgis.workspace.analysis.pipeline.MODULE_TASKS",
        mock_tasks,
        clear=True,
    ) as patched:
        yield patched


@pytest.fixture
def default_workspace() -> Workspace:
    """Default workspace with ``db_schema="public"``, matching the BDD Background."""
    return WorkspaceFactory(db_schema="public", name="BDD Default Workspace")

"""Property-based tests for deal contracts using hypothesis-generated inputs.

These tests use ``deal.cases()`` to automatically generate inputs from type
annotations and verify that all ``@deal.pre``, ``@deal.post``, ``@deal.ensure``
contracts hold.

Marked as ``@pytest.mark.slow`` because property-based tests are computationally
heavier than unit tests.  Skip with ``pytest -m "not slow"``.
"""

from __future__ import annotations

import os

import deal
import pytest

from brewgis.workspace.analysis.pipeline import resolve_module_order
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.lehd_fetcher import _apply_naics_splits
from brewgis.workspace.services.lehd_fetcher import _apply_sacog_calibrated_splits
from brewgis.workspace.services.lehd_fetcher import _compute_aggregate_employment
from brewgis.workspace.services.paint_constraints import _evaluate
from brewgis.workspace.symbology.classifiers import _equal_interval_breaks
from brewgis.workspace.symbology.classifiers import _fmt
from brewgis.workspace.symbology.classifiers import _logarithmic_breaks
from brewgis.workspace.symbology.classifiers import _make_labels
from brewgis.workspace.symbology.classifiers import _std_deviation_breaks
from brewgis.workspace.symbology.classifiers import _sum_squared_diffs
from brewgis.workspace.symbology.generator import _normalize_geo

# Seed for deterministic CI runs — use CI_PIPELINE_ID, GITHUB_RUN_ID, or similar
_DEAL_SEED_RAW = os.environ.get("DEAL_SEED")
_DEAL_SEED: int | None = int(_DEAL_SEED_RAW) if _DEAL_SEED_RAW else None
_DEAL_CASE_COUNT_RAW = os.environ.get("DEAL_CASE_COUNT")
_DEAL_CASE_COUNT: int = int(_DEAL_CASE_COUNT_RAW) if _DEAL_CASE_COUNT_RAW else 25

# ---------------------------------------------------------------------------
# Classifier contracts
# ---------------------------------------------------------------------------


@pytest.mark.slow
@deal.cases(_equal_interval_breaks, count=_DEAL_CASE_COUNT, seed=_DEAL_SEED)
def test_equal_interval_breaks_contract(case: deal.TestCase) -> None:
    case()


@pytest.mark.slow
@deal.cases(_logarithmic_breaks, count=_DEAL_CASE_COUNT, seed=_DEAL_SEED)
def test_logarithmic_breaks_contract(case: deal.TestCase) -> None:
    case()


@pytest.mark.slow
@deal.cases(_std_deviation_breaks, count=_DEAL_CASE_COUNT, seed=_DEAL_SEED)
def test_std_deviation_breaks_contract(case: deal.TestCase) -> None:
    case()


@pytest.mark.slow
@deal.cases(_sum_squared_diffs, count=_DEAL_CASE_COUNT, seed=_DEAL_SEED)
def test_sum_squared_diffs_contract(case: deal.TestCase) -> None:
    case()


@pytest.mark.slow
@deal.cases(_fmt, count=_DEAL_CASE_COUNT, seed=_DEAL_SEED)
def test_fmt_contract(case: deal.TestCase) -> None:
    case()


@pytest.mark.slow
@deal.cases(_make_labels, count=_DEAL_CASE_COUNT, seed=_DEAL_SEED)
def test_make_labels_contract(case: deal.TestCase) -> None:
    case()


# Stitcher: ``impute_constant`` is excluded from property-based testing
# because it runs SQL queries against the database.  Hypothesis-generated
# table/column names would fail.  The contract is still enforced at runtime
# by ``deal.enable()`` during integration tests.

# ---------------------------------------------------------------------------
# Analysis pipeline contracts
# ---------------------------------------------------------------------------


@pytest.mark.slow
@deal.cases(resolve_module_order, count=_DEAL_CASE_COUNT, seed=_DEAL_SEED)
def test_resolve_module_order_contract(case: deal.TestCase) -> None:
    case()


# ---------------------------------------------------------------------------
# Symbology generator contracts
# ---------------------------------------------------------------------------


@pytest.mark.slow
@deal.cases(_normalize_geo, count=_DEAL_CASE_COUNT, seed=_DEAL_SEED)
def test_normalize_geo_contract(case: deal.TestCase) -> None:
    case()


# ---------------------------------------------------------------------------
# Paint constraint contracts
# ---------------------------------------------------------------------------


@pytest.mark.slow
@deal.cases(_evaluate, count=_DEAL_CASE_COUNT, seed=_DEAL_SEED)
def test_evaluate_contract(case: deal.TestCase) -> None:
    case()


# ---------------------------------------------------------------------------
# LEHD fetcher contracts
# ---------------------------------------------------------------------------


@pytest.mark.slow
@deal.cases(_apply_naics_splits, count=_DEAL_CASE_COUNT, seed=_DEAL_SEED)
def test_apply_naics_splits_contract(case: deal.TestCase) -> None:
    case()


@pytest.mark.slow
@deal.cases(_apply_sacog_calibrated_splits, count=_DEAL_CASE_COUNT, seed=_DEAL_SEED)
def test_apply_sacog_calibrated_splits_contract(case: deal.TestCase) -> None:
    case()


@pytest.mark.slow
@deal.cases(_compute_aggregate_employment, count=_DEAL_CASE_COUNT, seed=_DEAL_SEED)
def test_compute_aggregate_employment_contract(case: deal.TestCase) -> None:
    case()
def test_create_table_sql_contains_table_name() -> None:
    """Verify create_table_sql embeds the table_name."""
    sql = BaseCanvasSchema.create_table_sql("fresno_demo.test_canvas")
    assert "fresno_demo.test_canvas" in sql


def test_create_table_sql_defaults_to_public_base_canvas() -> None:
    """Verify create_table_sql defaults to public.base_canvas."""
    sql = BaseCanvasSchema.create_table_sql()
    assert "public.base_canvas" in sql


def test_create_indexes_sql_contains_table_name() -> None:
    """Verify create_indexes_sql embeds the table_name in all statements."""
    stmts = BaseCanvasSchema.create_indexes_sql("fresno_demo.test_canvas")
    for stmt in stmts:
        assert "fresno_demo.test_canvas" in stmt


def test_create_indexes_sql_defaults_to_public_base_canvas() -> None:
    """Verify create_indexes_sql defaults to public.base_canvas."""
    stmts = BaseCanvasSchema.create_indexes_sql()
    for stmt in stmts:
        assert "public.base_canvas" in stmt

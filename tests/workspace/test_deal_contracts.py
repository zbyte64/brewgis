"""Deal contract checks for production helpers.

``make test-deal`` runs this file with ``DEAL_ENABLED=1``, which turns on the
``@deal.pre`` / ``@deal.post`` / ``@deal.ensure`` contracts the modules carry
(the rest of the suite disables them — see ``tests/conftest.py``). The
property-based cases are skipped without it: with the checks off, a
``@deal.raises(ValueError)`` contract is not honoured and the generated inputs
would fail the run.
"""

from __future__ import annotations

import os

import deal
import pytest

from brewgis.workspace.analysis.pipeline import resolve_module_order
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.symbology.classifiers import _fmt
from brewgis.workspace.symbology.classifiers import _make_labels
from brewgis.workspace.symbology.generator import _normalize_geo

_DEAL_ENABLED = os.environ.get("DEAL_ENABLED") == "1"
_SEED_RAW = os.environ.get("DEAL_SEED")
_SEED: int | None = int(_SEED_RAW) if _SEED_RAW else None
_CASE_COUNT = int(os.environ.get("DEAL_CASE_COUNT", "25"))

_requires_deal = pytest.mark.skipif(
    not _DEAL_ENABLED, reason="deal contracts run only with DEAL_ENABLED=1"
)


@pytest.mark.slow
@_requires_deal
@deal.cases(_fmt, count=_CASE_COUNT, seed=_SEED)
def test_fmt_contract(case: deal.TestCase) -> None:
    case()


@pytest.mark.slow
@_requires_deal
@deal.cases(_make_labels, count=_CASE_COUNT, seed=_SEED)
def test_make_labels_contract(case: deal.TestCase) -> None:
    case()


@pytest.mark.slow
@_requires_deal
@deal.cases(_normalize_geo, count=_CASE_COUNT, seed=_SEED)
def test_normalize_geo_contract(case: deal.TestCase) -> None:
    case()


@pytest.mark.slow
@_requires_deal
@deal.cases(resolve_module_order, count=_CASE_COUNT, seed=_SEED)
def test_resolve_module_order_contract(case: deal.TestCase) -> None:
    case()


def test_create_table_sql_contains_table_name() -> None:
    """``create_table_sql`` embeds the table name."""
    sql = BaseCanvasSchema.create_table_sql("fresno_demo.test_canvas")
    assert "fresno_demo.test_canvas" in sql


def test_create_table_sql_defaults_to_public_base_canvas() -> None:
    """``create_table_sql`` defaults to ``public.base_canvas``."""
    assert "public.base_canvas" in BaseCanvasSchema.create_table_sql()


def test_create_indexes_sql_contains_table_name() -> None:
    """``create_indexes_sql`` embeds the table name in every statement."""
    stmts = BaseCanvasSchema.create_indexes_sql("fresno_demo.test_canvas")
    assert stmts
    for stmt in stmts:
        assert "fresno_demo.test_canvas" in stmt


def test_create_indexes_sql_defaults_to_public_base_canvas() -> None:
    """``create_indexes_sql`` defaults to ``public.base_canvas``."""
    stmts = BaseCanvasSchema.create_indexes_sql()
    assert stmts
    for stmt in stmts:
        assert "public.base_canvas" in stmt


def test_column_units_are_a_known_display_vocabulary() -> None:
    """Every column's unit is one of the units the UI knows how to render.

    Catches a naming convention misfiring on a column (e.g. an ``area_*``
    count being labelled "acres") rather than pinning each column's value.
    """
    units = {BaseCanvasSchema.unit(name) for name in BaseCanvasSchema.COLUMN_NAMES}
    assert units == {"", "acres", "sq ft", "%", "$/yr", "intersections/sq mi"}


def test_column_units_cover_area_building_currency_and_percent() -> None:
    """Representative columns carry the unit their name implies."""
    assert BaseCanvasSchema.unit("area_parcel") == "acres"
    assert BaseCanvasSchema.unit("residential_irrigated_area") == "acres"
    assert BaseCanvasSchema.unit("bldg_area_mf") == "sq ft"
    assert BaseCanvasSchema.unit("median_income") == "$/yr"
    assert BaseCanvasSchema.unit("rent_burden_pct") == "%"
    assert BaseCanvasSchema.unit("pct_minority") == "%"
    assert BaseCanvasSchema.unit("intersection_density") == "intersections/sq mi"


def test_counts_and_unknown_columns_have_no_unit() -> None:
    """Counts stay bare, and a column the schema doesn't define is never guessed."""
    for name in ("pop", "du", "emp_ret", "parcel_id", "built_form_key"):
        assert BaseCanvasSchema.unit(name) == ""
    assert BaseCanvasSchema.unit("vmt_total") == ""

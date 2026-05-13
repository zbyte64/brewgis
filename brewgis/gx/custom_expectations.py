"""Custom Great Expectations for Brew GIS-specific data quality checks.

Built-in GX Expectations cover most needs (null checks, range checks, schema
validation). These custom expectations handle PostGIS-specific and transport-
model-specific validation.

Each custom expectation is a subclass of ``gx.expectations.Expectation``.
"""

from __future__ import annotations

import logging

import great_expectations.expectations as gxe
from great_expectations.expectations.expectation import ColumnMapExpectation

logger = logging.getLogger(__name__)


# ── 1. PostGIS Geometry Validity ───────────────────────────────────


class ExpectPostgisGeometryValid(ColumnMapExpectation):
    """Expect PostGIS geometry column values to be valid (ST_IsValid).

    This expectation runs ``ST_IsValid(geometry)`` via a SQL query and
    checks that every row returns ``True``.

    Examples:
        >>> ExpectPostgisGeometryValid(column="geometry")
    """

    description = "Expect PostGIS geometry values to be valid."

    column_types = ["geometry", "GEOMETRY"]

    success_keys = ("mostly",)

    default_kwarg_values = {
        "mostly": 1.0,
    }

    map_metric = "postgis.geometry_is_valid"


class ExpectPostgisGeometrySrid(ColumnMapExpectation):
    """Expect PostGIS geometry column to have a specific SRID.

    Args:
        column: Geometry column name.
        value: Expected SRID (default 4326).
    """

    description = "Expect PostGIS geometry values to have a specific SRID."

    column_types = ["geometry", "GEOMETRY"]

    success_keys = ("value", "mostly")

    default_kwarg_values = {
        "value": 4326,
        "mostly": 1.0,
    }

    map_metric = "postgis.geometry_srid"


# ── 2. Column Sum Conservation ──────────────────────────────────────


class ExpectColumnSumConservation(gxe.Expectation):
    """Expect the sum of one column to approximately equal the sum of another.

    Useful for trip conservation checks (outbound trips = inbound + internal)
    and allocation integrity (source total = allocated total).

    Args:
        column_A: Source column name.
        column_B: Target column name.
        tolerance: Maximum relative difference (default 0.05 = 5%).
    """

    description = "Expect the sum of column A to approximately equal the sum of column B."

    success_keys = ("column_A", "column_B", "tolerance")

    default_kwarg_values = {
        "tolerance": 0.05,
    }


# ── 3. Mode Shares Sum to One ──────────────────────────────────────


class ExpectModeSharesSumToOne(gxe.Expectation):
    """Expect per-row mode share columns to sum to approximately 1.0.

    Args:
        mode_columns: List of mode share column names.
        tolerance: Maximum per-row deviation from 1.0 (default 0.01).
    """

    description = "Expect per-row mode share proportions to sum to approximately 1.0."

    success_keys = ("mode_columns", "tolerance")

    default_kwarg_values = {
        "tolerance": 0.01,
    }

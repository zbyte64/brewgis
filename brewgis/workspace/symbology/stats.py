"""Column statistics from PostGIS for symbology auto-classification.

Queries are executed directly against the database to avoid loading
large feature tables into Python memory.  Statistics include counts,
distribution percentiles, and type heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import connection


@dataclass
class ColumnStatistics:
    """Aggregate statistics for a single feature column.

    For categorical columns (``is_categorical == True``), only
    *column_name*, *data_type*, *count*, *null_count*, *distinct_count*,
    and *frequencies* are populated; numeric measures are ``None``.
    """

    column_name: str
    data_type: str
    count: int
    null_count: int
    distinct_count: int
    min_value: float | None = None
    max_value: float | None = None
    mean: float | None = None
    median: float | None = None
    stddev: float | None = None
    percentiles: dict[int, float] | None = None
    frequencies: dict[str, int] | None = None
    is_categorical: bool = False


_NUMERIC_TYPES = frozenset(
    {
        # SQL-standard names (udt_name from information_schema)
        "smallint",
        "integer",
        "bigint",
        "real",
        "double precision",
        "numeric",
        "decimal",
        # PostgreSQL internal names
        "int2",
        "int4",
        "int8",
        "float4",
        "float8",
    }
)


def _column_data_type(schema: str, table: str, column: str) -> str | None:
    """Return the PostGIS data type of *column* or ``None``."""
    sql = """
        SELECT udt_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [schema, table, column])
        row = cursor.fetchone()
    return row[0] if row else None


def compute_statistics(
    schema: str,
    table: str,
    column: str,
    *,
    exclude_zero: bool = False,
) -> ColumnStatistics:
    """Compute column statistics from a PostGIS table.

    Parameters
    ----------
    schema:
        Database schema (e.g. ``"public"``).
    table:
        Table name.
    column:
        Column name.
    exclude_zero:
        Leave rows whose value is exactly 0 out of the statistics. That is
        what the symbology's "Zero Transparent" option draws as invisible, and
        a hidden value must not steer the classification: a zero-inflated
        column would otherwise spend its classes on the zero mass (the whole
        column, for the methods that read these statistics) instead of on the
        values the map actually shows. A non-numeric column has no zero to
        exclude, so the flag is ignored for it.

    Returns
    -------
    ColumnStatistics
        Populated statistics object.
    """
    data_type = _column_data_type(schema, table, column) or "unknown"
    is_numeric = data_type in _NUMERIC_TYPES
    exclude_zero = exclude_zero and is_numeric
    included = f' AND "{column}" <> 0' if exclude_zero else ""
    included_distincts = (
        f'COUNT(DISTINCT "{column}") FILTER (WHERE "{column}" <> 0)'
        if exclude_zero
        else f'COUNT(DISTINCT "{column}")'
    )

    # Base query - always available
    base_sql = f"""
        SELECT
            COUNT(*)                                                     AS total,
            COUNT(*) FILTER (WHERE "{column}" IS NULL)                   AS nulls,
            COUNT(DISTINCT "{column}")                                   AS distincts,
            {included_distincts}                                         AS included_distincts
        FROM "{schema}"."{table}"
    """  # noqa: S608 -- identifiers are catalog-sourced, never user input
    with connection.cursor() as cursor:
        cursor.execute(base_sql)
        total, nulls, distincts, distincts_included = cursor.fetchone()

    if exclude_zero:
        distincts = distincts_included

    freq: dict[str, int] | None = None
    if distincts <= 50:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT "{column}"::text, COUNT(*)
                FROM "{schema}"."{table}"
                WHERE "{column}" IS NOT NULL{included}
                GROUP BY "{column}"
                ORDER BY COUNT(*) DESC
                LIMIT 100
                """  # noqa: S608 -- identifiers are catalog-sourced, never user input,
            )
            freq = dict(cursor.fetchall())

    if not is_numeric:
        return ColumnStatistics(
            column_name=column,
            data_type=data_type,
            count=total,
            null_count=nulls,
            distinct_count=distincts,
            is_categorical=not is_numeric,
            frequencies=freq,
        )

    stats_sql = f"""
        SELECT
            MIN("{column}")::double precision                              AS min_val,
            MAX("{column}")::double precision                              AS max_val,
            AVG("{column}")::double precision                              AS mean,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "{column}")::double precision AS median,
            STDDEV_SAMP("{column}")::double precision                      AS stddev
        FROM "{schema}"."{table}"
        WHERE "{column}" IS NOT NULL{included}
    """  # noqa: S608 -- identifiers are catalog-sourced, never user input
    with connection.cursor() as cursor:
        cursor.execute(stats_sql)
        min_val, max_val, mean, median, stddev = cursor.fetchone()

    # Percentiles
    percentile_sql = f"""
        SELECT
            PERCENTILE_CONT(0.1) WITHIN GROUP (ORDER BY "{column}")::double precision AS p10,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY "{column}")::double precision AS p25,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "{column}")::double precision AS p50,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "{column}")::double precision AS p75,
            PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY "{column}")::double precision AS p90
        FROM "{schema}"."{table}"
        WHERE "{column}" IS NOT NULL{included}
    """  # noqa: S608 -- identifiers are catalog-sourced, never user input
    with connection.cursor() as cursor:
        cursor.execute(percentile_sql)
        p10, p25, p50, p75, p90 = cursor.fetchone()
    percentiles: dict[int, float] = {
        10: p10,
        25: p25,
        50: p50,
        75: p75,
        90: p90,
    }

    # Heuristic: if distinct count is small (<20), treat as categorical
    is_cat = distincts < 20

    return ColumnStatistics(
        column_name=column,
        data_type=data_type,
        count=int(total),
        null_count=int(nulls),
        distinct_count=int(distincts),
        min_value=min_val,
        max_value=max_val,
        mean=mean,
        median=median,
        stddev=stddev,
        percentiles=percentiles,
        frequencies=freq,
        is_categorical=is_cat or not is_numeric,
    )


def list_columns(schema: str, table: str) -> list[dict[str, Any]]:
    """List column names and data types for a given table.

    Returns a list of dicts with keys ``name`` and ``type``.
    """
    sql = """
        SELECT column_name, udt_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [schema, table])
        return [{"name": r[0], "type": r[1]} for r in cursor.fetchall()]

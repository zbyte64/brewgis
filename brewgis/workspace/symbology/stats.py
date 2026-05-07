"""Column statistics from PostGIS for symbology auto-classification.

Queries are executed directly against the database to avoid loading
large feature tables into Python memory.  Statistics include counts,
distribution percentiles, histograms, and type heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import connection


@dataclass
class HistogramBin:
    """A single histogram bucket."""

    min_val: float
    max_val: float
    count: int


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
    histogram: list[HistogramBin] | None = None
    percentiles: dict[int, float] | None = None
    frequencies: dict[str, int] | None = None
    is_categorical: bool = False


_NUMERIC_TYPES = frozenset({
    "smallint",
    "integer",
    "bigint",
    "real",
    "double precision",
    "numeric",
    "decimal",
})


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
    num_histogram_bins: int = 10,
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
    num_histogram_bins:
        Number of histogram buckets (default 10; used only for numeric columns).

    Returns
    -------
    ColumnStatistics
        Populated statistics object.
    """
    data_type = _column_data_type(schema, table, column) or "unknown"
    is_numeric = data_type in _NUMERIC_TYPES

    # Base query - always available
    base_sql = f"""
        SELECT
            COUNT(*)                                                     AS total,
            COUNT(*) FILTER (WHERE "{column}" IS NULL)                   AS nulls,
            COUNT(DISTINCT "{column}")                                   AS distincts
        FROM "{schema}"."{table}"
    """
    with connection.cursor() as cursor:
        cursor.execute(base_sql)
        total, nulls, distincts = cursor.fetchone()

    freq: dict[str, int] | None = None
    if distincts <= 50:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT "{column}"::text, COUNT(*)
                FROM "{schema}"."{table}"
                WHERE "{column}" IS NOT NULL
                GROUP BY "{column}"
                ORDER BY COUNT(*) DESC
                LIMIT 100
                """,
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

    epsilon = 1e-12
    stats_sql = f"""
        SELECT
            MIN("{column}")::double precision                              AS min_val,
            MAX("{column}")::double precision                              AS max_val,
            AVG("{column}")::double precision                              AS mean,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "{column}")::double precision AS median,
            STDDEV_SAMP("{column}")::double precision                      AS stddev
        FROM "{schema}"."{table}"
        WHERE "{column}" IS NOT NULL
    """
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
        WHERE "{column}" IS NOT NULL
    """
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

    # Histogram
    histogram: list[HistogramBin] = []
    if min_val is not None and max_val is not None and max_val - min_val > epsilon:
        hist_sql = f"""
            WITH bounds AS (
                SELECT
                    MIN("{column}") AS min_v,
                    MAX("{column}") AS max_v
                FROM "{schema}"."{table}"
                WHERE "{column}" IS NOT NULL
            )
            SELECT
                min_v + (max_v - min_v) * (bin - 1) / {num_histogram_bins}::double precision AS bin_min,
                min_v + (max_v - min_v) * bin / {num_histogram_bins}::double precision AS bin_max,
                COUNT(*) AS cnt
            FROM bounds
            CROSS JOIN LATERAL (
                SELECT WIDTH_BUCKET("{column}", min_v, max_v * (1 + 1e-10), {num_histogram_bins}) AS bin
                FROM "{schema}"."{table}"
                WHERE "{column}" IS NOT NULL
            ) b
            WHERE bin IS NOT NULL
            GROUP BY bin, bin_min, bin_max
            ORDER BY bin
        """
        with connection.cursor() as cursor:
            cursor.execute(hist_sql)
            for row in cursor.fetchall():
                histogram.append(HistogramBin(
                    min_val=float(row[0]),
                    max_val=float(row[1]),
                    count=int(row[2]),
                ))

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
        histogram=histogram or None,
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

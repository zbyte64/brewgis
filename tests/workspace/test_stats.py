# ruff: noqa: ARG002
"""Tests for symbology statistics computation.

Tests ``compute_statistics``, ``list_columns``, and ``_column_data_type``
from ``brewgis.workspace.symbology.stats``.
"""

from __future__ import annotations

import math

import pytest
from django.db import connection

from brewgis.workspace.symbology.stats import ColumnStatistics
from brewgis.workspace.symbology.stats import HistogramBin
from brewgis.workspace.symbology.stats import _column_data_type
from brewgis.workspace.symbology.stats import compute_statistics
from brewgis.workspace.symbology.stats import list_columns


@pytest.fixture
def numeric_table(db) -> str:
    """Create a table with known numeric data (values 1-10)."""
    table_name = "test_stats_numeric"
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cursor.execute(f"""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                value DOUBLE PRECISION
            )
        """)
        cursor.execute(
            f"INSERT INTO {table_name} (value) SELECT generate_series(1, 10)"
        )
    yield table_name
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")


@pytest.fixture
def empty_table(db) -> str:
    """Create a table with no rows."""
    table_name = "test_stats_empty"
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cursor.execute(f"""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                value DOUBLE PRECISION
            )
        """)
    yield table_name
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")


@pytest.fixture
def null_table(db) -> str:
    """Create a table containing NULL values in the measured column."""
    table_name = "test_stats_nulls"
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cursor.execute(f"""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                value DOUBLE PRECISION
            )
        """)
        cursor.execute(
            f"INSERT INTO {table_name} (id, value) VALUES "  # noqa: S608
            "(1, 1), (2, 2), (3, NULL), (4, 4), (5, 5)"
        )
    yield table_name
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")


@pytest.fixture
def all_nulls_table(db) -> str:
    """Create a table where all values in the measured column are NULL."""
    table_name = "test_stats_all_nulls"
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cursor.execute(f"""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                value DOUBLE PRECISION
            )
        """)
        cursor.execute(
            f"INSERT INTO {table_name} (id, value) VALUES "  # noqa: S608
            "(1, NULL), (2, NULL), (3, NULL)"
        )
    yield table_name
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")


@pytest.fixture
def categorical_table(db) -> str:
    """Create a table with few distinct text values (categorical)."""
    table_name = "test_stats_cat"
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cursor.execute(f"""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                label VARCHAR(10)
            )
        """)
        cursor.execute(
            f"INSERT INTO {table_name} (label) VALUES "  # noqa: S608
            "('A'), ('A'), ('B'), ('B'), ('C')"
        )
    yield table_name
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")


@pytest.fixture
def high_card_table(db) -> str:
    """Create a table with many distinct values (non-categorical heuristic)."""
    table_name = "test_stats_high_card"
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cursor.execute(f"""
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                value DOUBLE PRECISION
            )
        """)
        cursor.execute(
            f"INSERT INTO {table_name} (value) SELECT generate_series(1, 30)"
        )
    yield table_name
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")


# ---------------------------------------------------------------------------
# _column_data_type
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestColumnDataType:
    """Tests for :func:`_column_data_type`."""

    def test_known_column(self, numeric_table: str) -> None:
        dtype = _column_data_type("public", numeric_table, "value")
        assert dtype == "float8"

    def test_serial_column(self, numeric_table: str) -> None:
        dtype = _column_data_type("public", numeric_table, "id")
        assert dtype == "int4"

    def test_unknown_column(self, numeric_table: str) -> None:
        dtype = _column_data_type("public", numeric_table, "nonexistent")
        assert dtype is None

    def test_unknown_table(self, db) -> None:
        dtype = _column_data_type("public", "no_such_table", "value")
        assert dtype is None

    def test_varchar_column(self, categorical_table: str) -> None:
        dtype = _column_data_type("public", categorical_table, "label")
        assert dtype == "varchar"


# ---------------------------------------------------------------------------
# list_columns
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListColumns:
    """Tests for :func:`list_columns`."""

    def test_lists_names_and_types(self, numeric_table: str) -> None:
        cols = list_columns("public", numeric_table)
        names = [c["name"] for c in cols]
        assert "id" in names
        assert "value" in names

        id_col = next(c for c in cols if c["name"] == "id")
        assert id_col["type"] == "int4"

        val_col = next(c for c in cols if c["name"] == "value")
        assert val_col["type"] == "float8"

    def test_unknown_table(self, db) -> None:
        cols = list_columns("public", "nonexistent_table_xyz")
        assert cols == []

    def test_ordinal_order(self, numeric_table: str) -> None:
        cols = list_columns("public", numeric_table)
        assert cols[0]["name"] == "id"
        assert cols[1]["name"] == "value"


# ---------------------------------------------------------------------------
# compute_statistics
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestComputeStatistics:
    """Tests for :func:`compute_statistics`."""

    def test_basic_numeric_stats(self, numeric_table: str) -> None:
        """Verify min, max, mean, median, stddev on 1..10."""
        stats = compute_statistics("public", numeric_table, "value")
        assert isinstance(stats, ColumnStatistics)
        assert stats.column_name == "value"
        assert stats.data_type == "float8"
        assert stats.count == 10
        assert stats.null_count == 0
        assert stats.distinct_count == 10
        assert stats.min_value == 1.0
        assert stats.max_value == 10.0
        assert stats.mean == 5.5
        assert stats.median == 5.5
        assert stats.stddev is not None
        assert math.isclose(stats.stddev, math.sqrt(82.5 / 9), rel_tol=1e-10)
        # 10 distinct values < 20 → heuristic marks as categorical
        assert stats.is_categorical

    def test_percentiles(self, numeric_table: str) -> None:
        """Verify percentile boundaries for 1..10."""
        stats = compute_statistics("public", numeric_table, "value")
        assert stats.percentiles is not None
        assert math.isclose(stats.percentiles[10], 1.9, rel_tol=1e-10)
        assert math.isclose(stats.percentiles[25], 3.25, rel_tol=1e-10)
        assert math.isclose(stats.percentiles[50], 5.5, rel_tol=1e-10)
        assert math.isclose(stats.percentiles[75], 7.75, rel_tol=1e-10)
        assert math.isclose(stats.percentiles[90], 9.1, rel_tol=1e-10)

    def test_histogram(self, numeric_table: str) -> None:
        """Verify each of ten bins contains exactly one value for 1..10."""
        stats = compute_statistics(
            "public", numeric_table, "value", num_histogram_bins=10
        )
        assert stats.histogram is not None
        assert len(stats.histogram) == 10
        for bin_ in stats.histogram:
            assert isinstance(bin_, HistogramBin)
            assert bin_.count == 1
        # First bin starts at min and last bin includes max
        assert stats.histogram[0].min_val == 1.0
        assert math.isclose(stats.histogram[-1].max_val, 10.0, rel_tol=1e-10)

    def test_histogram_fewer_bins(self, numeric_table: str) -> None:
        """Verify histogram with 2 bins on 1..10."""
        stats = compute_statistics(
            "public", numeric_table, "value", num_histogram_bins=2
        )
        assert stats.histogram is not None
        assert len(stats.histogram) == 2
        assert stats.histogram[0].count + stats.histogram[1].count == 10

    def test_frequencies(self, numeric_table: str) -> None:
        """Verify frequencies when distinct count <= 50."""
        stats = compute_statistics("public", numeric_table, "value")
        assert stats.frequencies is not None
        assert stats.frequencies["1"] == 1
        assert stats.frequencies["5"] == 1
        assert stats.frequencies["10"] == 1
        assert len(stats.frequencies) == 10

    def test_with_nulls(self, null_table: str) -> None:
        """Verify correct count/null_count when some values are NULL."""
        stats = compute_statistics("public", null_table, "value")
        assert stats.count == 5
        assert stats.null_count == 1
        assert stats.distinct_count == 4
        assert stats.min_value == 1.0
        assert stats.max_value == 5.0
        assert stats.mean == 3.0  # (1+2+4+5)/4
        assert stats.median == 3.0  # percentile_cont(0.5) of [1,2,4,5]

    def test_all_nulls(self, all_nulls_table: str) -> None:
        """Verify handling when all values in the column are NULL."""
        stats = compute_statistics("public", all_nulls_table, "value")
        assert stats.count == 3
        assert stats.null_count == 3
        assert stats.distinct_count == 0  # NULLs are not counted by COUNT(DISTINCT)
        assert stats.min_value is None
        assert stats.max_value is None
        assert stats.mean is None
        assert stats.median is None
        assert stats.stddev is None
        assert stats.histogram is None
        assert stats.percentiles is not None
        assert stats.percentiles[10] is None
        assert (
            stats.frequencies == {}
        )  # distinct=0 <= 50, frequency query runs but returns nothing

    def test_empty_table(self, empty_table: str) -> None:
        """Verify behavior for a table with no rows."""
        stats = compute_statistics("public", empty_table, "value")
        assert stats.count == 0
        assert stats.null_count == 0
        assert stats.distinct_count == 0
        assert stats.min_value is None
        assert stats.max_value is None
        assert stats.mean is None
        assert stats.median is None
        assert stats.histogram is None
        assert (
            stats.frequencies == {}
        )  # distinct=0 <= 50, frequency query runs but returns nothing

    def test_categorical_detection(self, categorical_table: str) -> None:
        """Verify text column with few values is marked categorical."""
        stats = compute_statistics("public", categorical_table, "label")
        assert stats.is_categorical
        assert stats.data_type == "varchar"
        assert stats.count == 5
        assert stats.null_count == 0
        assert stats.distinct_count == 3
        # Numeric stats should be None for non-numeric columns
        assert stats.min_value is None
        assert stats.max_value is None
        assert stats.mean is None
        assert stats.median is None
        assert stats.stddev is None
        assert stats.histogram is None

    def test_categorical_frequencies(self, categorical_table: str) -> None:
        """Verify frequency map for categorical data."""
        stats = compute_statistics("public", categorical_table, "label")
        assert stats.frequencies is not None
        assert stats.frequencies["A"] == 2
        assert stats.frequencies["B"] == 2
        assert stats.frequencies["C"] == 1

    def test_high_cardinality_non_categorical(self, high_card_table: str) -> None:
        """Verify column with >=20 distinct values is not categorical."""
        stats = compute_statistics("public", high_card_table, "value")
        assert not stats.is_categorical
        assert stats.distinct_count == 30
        assert stats.frequencies is not None  # 30 <= 50, so still computed
        assert len(stats.frequencies) == 30
        assert stats.min_value == 1.0
        assert stats.max_value == 30.0

    def test_non_existent_table(self, db) -> None:
        """Verify graceful error on missing table."""
        with pytest.raises(Exception, match=r"relation .* does not exist"):
            compute_statistics("public", "no_such_table_xyz", "value")

    def test_column_name_needs_quoting(self, db) -> None:
        """Column names that need quoting are handled correctly."""
        # Create a column with a mixed-case name that requires quoting
        table_name = "test_stats_case_col"
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
            cursor.execute(f"""
                CREATE TABLE {table_name} (
                    id SERIAL PRIMARY KEY,
                    "MyValue" DOUBLE PRECISION
                )
            """)
            cursor.execute(
                f'INSERT INTO {table_name} ("MyValue") SELECT generate_series(1, 5)'
            )
        try:
            stats = compute_statistics("public", table_name, "MyValue")
            assert stats.count == 5
            assert stats.min_value == 1.0
            assert stats.max_value == 5.0
            assert stats.mean == 3.0
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")

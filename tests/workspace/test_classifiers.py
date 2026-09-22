"""Tests for the BrewGIS classification engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from django.db import connection

from brewgis.workspace.symbology.classifiers import ClassificationResult
from brewgis.workspace.symbology.classifiers import _equal_interval_breaks
from brewgis.workspace.symbology.classifiers import _logarithmic_breaks
from brewgis.workspace.symbology.classifiers import _make_labels
from brewgis.workspace.symbology.classifiers import _natural_breaks_points
from brewgis.workspace.symbology.classifiers import _quantile_breaks
from brewgis.workspace.symbology.classifiers import _std_deviation_breaks
from brewgis.workspace.symbology.classifiers import _weighted_natural_breaks
from brewgis.workspace.symbology.classifiers import classify
from brewgis.workspace.symbology.stats import compute_statistics

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass
class FakeStats:
    """Minimal duck-type of ColumnStatistics for testing."""

    min_value: float | None = 0.0
    max_value: float | None = 100.0
    mean: float | None = 50.0
    median: float | None = 50.0
    stddev: float | None = 20.0
    count: int = 0


class TestEqualInterval:
    def test_basic(self) -> None:
        breaks = _equal_interval_breaks(0, 100, 5)
        assert len(breaks) == 6
        assert breaks[0] == 0
        assert breaks[-1] == 100

    def test_single_class(self) -> None:
        breaks = _equal_interval_breaks(10, 20, 1)
        assert breaks == [10, 20]

    def test_zero_classes(self) -> None:
        breaks = _equal_interval_breaks(5, 10, 0)
        assert breaks == [5]

    def test_degenerate_range(self) -> None:
        breaks = _equal_interval_breaks(42, 42, 5)
        assert len(breaks) == 6
        assert all(b == 42 for b in breaks)


class TestLogarithmic:
    def test_basic(self) -> None:
        breaks = _logarithmic_breaks(1, 1000, 4)
        assert len(breaks) == 5
        assert breaks[0] == 1
        assert breaks[-1] == 1000

    def test_positive_domain(self) -> None:
        breaks = _logarithmic_breaks(10, 10000, 3)
        assert len(breaks) == 4
        assert breaks[0] == 10
        assert breaks[-1] == 10000

    def test_zero_min(self) -> None:
        breaks = _logarithmic_breaks(0, 100, 5)
        assert len(breaks) == 6
        assert breaks[0] == 0
        assert breaks[-1] == 100

    def test_zero_classes(self) -> None:
        breaks = _logarithmic_breaks(1, 100, 0)
        assert breaks == [1]


class TestStdDeviation:
    def test_basic(self) -> None:
        breaks = _std_deviation_breaks(50, 10, 5)
        assert len(breaks) == 6

    def test_odd_classes(self) -> None:
        breaks = _std_deviation_breaks(50, 10, 3)
        assert len(breaks) == 4  # n+1

    def test_zero_stddev(self) -> None:
        breaks = _std_deviation_breaks(50, 0, 5)
        assert len(breaks) == 6
        assert all(b == 50 for b in breaks)


def _points(values: list[float], weight: float = 1.0) -> list[tuple[float, float]]:
    """Weighted points for *values*, each standing for *weight* rows."""
    return [(value, weight) for value in values]


class TestWeightedNaturalBreaks:
    def test_basic(self) -> None:
        values = [1, 2, 4, 5, 7, 8, 10, 15, 20, 30]
        breaks = _weighted_natural_breaks(_points(values), 3)
        assert len(breaks) == 4  # one boundary per class, plus the maximum
        assert breaks[0] == values[0]
        assert breaks[-1] == values[-1]
        assert breaks == sorted(breaks)

    def test_uniform_data(self) -> None:
        breaks = _weighted_natural_breaks(_points(list(range(100))), 5)
        assert len(breaks) == 6

    def test_fewer_values_than_classes(self) -> None:
        breaks = _weighted_natural_breaks(_points([1, 5, 10]), 5)
        assert breaks == [1, 5, 10]

    def test_single_value(self) -> None:
        assert _weighted_natural_breaks(_points([42]), 3) == [42]

    def test_zero_classes(self) -> None:
        assert _weighted_natural_breaks(_points([1, 2, 3]), 0) == [1]

    def test_a_heavy_value_lands_in_its_own_class(self) -> None:
        """The weight is what isolates a value most of the column holds.

        One point standing for 900 of 903 rows belongs in its own class: any
        split that lumps it in with the three outliers pays their deviation
        once per row it stands for.
        """
        points = [(0.0, 900.0), (10.0, 1.0), (11.0, 1.0), (12.0, 1.0)]
        assert _weighted_natural_breaks(points, 2) == [0.0, 10.0, 12.0]

    def test_boundaries_are_distinct_even_when_values_tie(self) -> None:
        """A tied run can't produce two boundaries on one value.

        Equal-valued points are merged before the optimisation, so a boundary
        can never land inside a run of one repeated value — and the top class
        always spans two values, so the closing maximum never duplicates the
        class below it.
        """
        points = [(0.0, 500.0), (0.0, 400.0), (5.0, 1.0), (9.0, 1.0), (20.0, 1.0)]
        breaks = _weighted_natural_breaks(points, 3)
        assert len(breaks) == 4
        assert breaks[0] == 0.0
        assert breaks[-1] == 20.0
        assert len(set(breaks)) == len(breaks)


class TestMakeLabels:
    def test_basic(self) -> None:
        labels = _make_labels([0, 50, 100])
        assert len(labels) == 2
        assert "0" in labels[0]
        assert "50" in labels[1]

    def test_float_labels(self) -> None:
        labels = _make_labels([0.0, 33.3, 66.6, 100.0])
        assert len(labels) == 3

    def test_breaks_that_round_alike_stay_apart(self) -> None:
        """A class never reads as an empty range."""
        labels = _make_labels([0.0, 528.3417128571426, 528.3417128571431])
        assert labels[0] != labels[1]
        assert labels[0].split(" - ")[1] == labels[1].split(" - ")[0]


class TestClassifyFunction:
    def test_equal_interval(self) -> None:
        stats = FakeStats(min_value=0, max_value=100)
        result = classify(stats, method="equal_interval", num_classes=5)
        assert isinstance(result, ClassificationResult)
        assert len(result.breaks) == 6
        assert result.breaks[0] == 0
        assert result.breaks[-1] == 100
        assert len(result.labels) == 5

    def test_logarithmic(self) -> None:
        stats = FakeStats(min_value=1, max_value=1000)
        result = classify(stats, method="logarithmic", num_classes=4)
        assert len(result.breaks) == 5
        assert result.breaks[0] == 1
        assert result.breaks[-1] == 1000

    def test_std_deviation(self) -> None:
        stats = FakeStats(mean=50, stddev=10)
        result = classify(stats, method="std_deviation", num_classes=5)
        assert len(result.breaks) == 6

    def test_natural_breaks_requires_the_column(self) -> None:
        """Natural breaks reads the distribution, so it needs the identifiers."""
        stats = FakeStats(min_value=0, max_value=100)
        with pytest.raises(ValueError, match="natural breaks"):
            classify(stats, method="natural_breaks", num_classes=5)

    def test_quantile_requires_db(self) -> None:
        stats = FakeStats(min_value=0, max_value=100)
        with pytest.raises(ValueError, match="quantile"):
            classify(stats, method="quantile", num_classes=5)

    def test_manual_breaks(self) -> None:
        stats = FakeStats(min_value=0, max_value=100)
        result = classify(
            stats,
            method="manual",
            num_classes=3,
            manual_breaks=[0, 33, 66, 100],
        )
        assert result.breaks == [0, 33, 66, 100]

    def test_unknown_method(self) -> None:
        stats = FakeStats()
        with pytest.raises(ValueError, match="Unknown"):
            classify(stats, method="bogus", num_classes=5)


class TestEdgeCases:
    """Edge cases for classification functions."""

    def test_identical_values(self) -> None:
        """All-identical values handled by natural breaks and equal interval."""
        breaks = _weighted_natural_breaks([(5.0, 5.0)], 3)
        assert breaks == [5.0]

        breaks = _equal_interval_breaks(42, 42, 5)
        assert len(breaks) == 6
        assert all(b == 42 for b in breaks)

    def test_negative_values(self) -> None:
        """Negative values handled by logarithmic classifier."""
        breaks = _logarithmic_breaks(-50, 100, 5)
        assert len(breaks) == 6
        assert breaks[0] == -50
        assert breaks[-1] == 100

    def test_empty_values(self) -> None:
        """Empty value list handled by natural breaks classifier."""
        assert _weighted_natural_breaks([], 5) == [0.0]


@pytest.fixture
def tie_heavy_table(db) -> Iterator[tuple[str, str]]:
    """A table with a zero-inflated column — 81% of its rows share the value 0.

    That is the shape of a real analysis result (parcels with no activity in a
    VMT/trip table), and the shape that used to collapse quantile classes.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS test_quantile_ties "
            "(g integer PRIMARY KEY, value double precision)"
        )
        cursor.execute("TRUNCATE test_quantile_ties")
        cursor.execute(
            """
            INSERT INTO test_quantile_ties (g, value)
            SELECT g,
                   CASE WHEN g % 100 < 81 THEN 0.0 ELSE g::double precision END
            FROM generate_series(1, 1000) AS g
            """
        )
    yield "public", "test_quantile_ties"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_quantile_ties")


@pytest.fixture
def evenly_spread_table(db) -> Iterator[tuple[str, str]]:
    """A table with one distinct value per row, and no ties."""
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS test_quantile_even "
            "(g integer PRIMARY KEY, value double precision)"
        )
        cursor.execute("TRUNCATE test_quantile_even")
        cursor.execute(
            """
            INSERT INTO test_quantile_even (g, value)
            SELECT g, g::double precision FROM generate_series(1, 1000) AS g
            """
        )
    yield "public", "test_quantile_even"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_quantile_even")


class TestQuantileBreaks:
    """``_quantile_breaks`` against a live table."""

    def test_returns_the_requested_classes_for_an_even_distribution(
        self, evenly_spread_table: tuple[str, str]
    ) -> None:
        schema, table = evenly_spread_table
        breaks = _quantile_breaks(schema, table, "value", 5)
        assert breaks == [1.0, 200.0, 400.0, 600.0, 800.0, 1000.0]

    def test_ties_do_not_collapse_the_requested_classes(
        self, tie_heavy_table: tuple[str, str]
    ) -> None:
        """Regression: a zero-inflated column used to yield a single class.

        Every tile boundary landed on 0 (NTILE splits by row count, and 81% of
        the rows are 0), so deduplicating them left one class spanning the whole
        range — which renders the layer as a single flat color.
        """
        schema, table = tie_heavy_table
        breaks = _quantile_breaks(schema, table, "value", 5)
        assert len(breaks) == 6
        assert breaks == sorted(breaks)
        assert breaks[0] == 0.0
        # 1000 % 100 == 0, so that row is tied to 0 as well: 999 is the largest
        # value in the fixture, and the top class has to reach it.
        assert breaks[-1] == 999.0


class TestNaturalBreaks:
    """``classify(..., method="natural_breaks")`` against a live table."""

    def test_spans_the_data_on_an_even_distribution(
        self, evenly_spread_table: tuple[str, str]
    ) -> None:
        schema, table = evenly_spread_table
        stats = compute_statistics(schema, table, "value")
        result = classify(
            stats,
            method="natural_breaks",
            num_classes=5,
            schema=schema,
            table=table,
            column="value",
        )
        assert len(result.breaks) == 6
        assert result.breaks[0] == 1.0
        assert result.breaks[-1] == 1000.0
        assert result.breaks == sorted(result.breaks)
        assert len(set(result.breaks)) == len(result.breaks)

    def test_keeps_a_zero_inflated_mass_inside_the_breaks(
        self, tie_heavy_table: tuple[str, str]
    ) -> None:
        """Regression: 81% of the fixture's rows share the value 0.

        Reading the distribution off linear histogram midpoints put every
        break above that mass (and the interpolation fallback invented values
        beyond it), so the overwhelming majority of features belonged to no
        class at all.
        """
        schema, table = tie_heavy_table
        stats = compute_statistics(schema, table, "value")
        result = classify(
            stats,
            method="natural_breaks",
            num_classes=5,
            schema=schema,
            table=table,
            column="value",
        )
        assert len(result.breaks) == 6
        assert result.breaks[0] == 0.0
        assert result.breaks[-1] == 999.0
        assert result.breaks == sorted(result.breaks)
        assert len(set(result.breaks)) == len(result.breaks)

    def test_points_come_from_the_column(
        self, tie_heavy_table: tuple[str, str]
    ) -> None:
        """Sample points are real values, weighted by the rows they hold."""
        schema, table = tie_heavy_table
        points = _natural_breaks_points(schema, table, "value")

        assert points[0] == (0.0, points[0][1])
        assert points[0][1] > 500  # the tied mass, not one row
        assert points[-1][0] == 999.0
        assert [value for value, _weight in points] == sorted(
            value for value, _weight in points
        )


class TestExcludingZeros:
    """``exclude_zero`` — what a "Zero Transparent" symbology classifies."""

    def test_quantile_ignores_the_zero_mass(
        self, tie_heavy_table: tuple[str, str]
    ) -> None:
        schema, table = tie_heavy_table
        with_zeros = _quantile_breaks(schema, table, "value", 5)
        without_zeros = _quantile_breaks(schema, table, "value", 5, exclude_zero=True)

        assert with_zeros[0] == 0.0
        assert without_zeros[0] > 0.0
        assert len(without_zeros) == 6
        assert without_zeros == sorted(without_zeros)

    def test_natural_breaks_ignore_the_zero_mass(
        self, tie_heavy_table: tuple[str, str]
    ) -> None:
        schema, table = tie_heavy_table
        stats = compute_statistics(schema, table, "value", exclude_zero=True)
        result = classify(
            stats,
            method="natural_breaks",
            num_classes=5,
            schema=schema,
            table=table,
            column="value",
            exclude_zero=True,
        )

        assert len(result.breaks) == 6
        assert result.breaks[0] > 0.0
        assert result.breaks == sorted(result.breaks)
        assert len(set(result.breaks)) == len(result.breaks)

    def test_statistics_ignore_the_zero_mass(
        self, tie_heavy_table: tuple[str, str]
    ) -> None:
        schema, table = tie_heavy_table
        with_zeros = compute_statistics(schema, table, "value")
        without_zeros = compute_statistics(schema, table, "value", exclude_zero=True)

        assert with_zeros.min_value == 0.0
        assert without_zeros.min_value == 81.0
        assert without_zeros.median > 0
        assert without_zeros.distinct_count == with_zeros.distinct_count - 1
        # The row counts stay honest about the column itself.
        assert without_zeros.count == with_zeros.count
        assert without_zeros.null_count == with_zeros.null_count

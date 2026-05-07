"""Tests for the BrewGIS classification engine."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from brewgis.workspace.symbology.classifiers import (
    ClassificationResult,
    classify,
    _equal_interval_breaks,
    _logarithmic_breaks,
    _make_labels,
    _natural_breaks_jenks,
    _std_deviation_breaks,
)


@dataclass
class FakeStats:
    """Minimal duck-type of ColumnStatistics for testing."""

    min_value: float | None = 0.0
    max_value: float | None = 100.0
    mean: float | None = 50.0
    median: float | None = 50.0
    stddev: float | None = 20.0
    count: int = 0
    histogram: list | None = None


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


class TestNaturalBreaksJenks:
    def test_basic(self) -> None:
        values = [1, 2, 4, 5, 7, 8, 10, 15, 20, 30]
        breaks = _natural_breaks_jenks(values, 3)
        assert len(breaks) == 4  # n+1
        assert breaks[0] == values[0]
        assert breaks[-1] == values[-1]

    def test_uniform_data(self) -> None:
        values = list(range(100))
        breaks = _natural_breaks_jenks(values, 5)
        assert len(breaks) == 6

    def test_fewer_values_than_classes(self) -> None:
        values = [1, 5, 10]
        breaks = _natural_breaks_jenks(values, 5)
        assert len(breaks) <= len(set(values)) + 1

    def test_single_value(self) -> None:
        breaks = _natural_breaks_jenks([42], 3)
        assert breaks == [42]

    def test_zero_classes(self) -> None:
        breaks = _natural_breaks_jenks([1, 2, 3], 0)
        assert breaks == [1]


class TestMakeLabels:
    def test_basic(self) -> None:
        labels = _make_labels([0, 50, 100])
        assert len(labels) == 2
        assert "0" in labels[0]
        assert "50" in labels[1]

    def test_float_labels(self) -> None:
        labels = _make_labels([0.0, 33.3, 66.6, 100.0])
        assert len(labels) == 3


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

    def test_natural_breaks(self) -> None:
        stats = FakeStats(min_value=0, max_value=100, histogram=[])
        result = classify(stats, method="natural_breaks", num_classes=3)
        assert len(result.breaks) == 4

    def test_quantile_requires_db(self) -> None:
        stats = FakeStats(min_value=0, max_value=100)
        with pytest.raises(ValueError, match="quantile"):
            classify(stats, method="quantile", num_classes=5)

    def test_manual_breaks(self) -> None:
        stats = FakeStats(min_value=0, max_value=100)
        result = classify(
            stats, method="manual", num_classes=3,
            manual_breaks=[0, 33, 66, 100],
        )
        assert result.breaks == [0, 33, 66, 100]

    def test_unknown_method(self) -> None:
        stats = FakeStats()
        with pytest.raises(ValueError, match="Unknown"):
            classify(stats, method="bogus", num_classes=5)

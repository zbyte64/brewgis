"""Tests for the auto-generation pipeline."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from brewgis.workspace.models import Layer
from brewgis.workspace.models import Workspace
from brewgis.workspace.symbology.auto import _suggest_classification_method
from brewgis.workspace.symbology.auto import _suggest_palette
from brewgis.workspace.symbology.auto import _suggest_symbology_type
from brewgis.workspace.symbology.auto import auto_generate_symbology
from brewgis.workspace.symbology.stats import ColumnStatistics
from brewgis.workspace.symbology.classifiers import ClassificationResult


def _make_stats(
    is_categorical: bool = False,
    distinct_count: int = 100,
    min_value: float = 0.0,
    max_value: float = 100.0,
    mean: float = 50.0,
    median: float = 50.0,
    stddev: float = 20.0,
) -> ColumnStatistics:
    return ColumnStatistics(
        column_name="test_col",
        data_type="float8",
        count=1000,
        null_count=0,
        distinct_count=distinct_count,
        min_value=min_value,
        max_value=max_value,
        mean=mean,
        median=median,
        stddev=stddev,
        is_categorical=is_categorical,
    )


class TestSuggestionHeuristics:
    def test_categorical_type(self) -> None:
        stats = _make_stats(is_categorical=True)
        assert _suggest_symbology_type(stats) == "categorical"

    def test_graduated_type(self) -> None:
        stats = _make_stats(is_categorical=False, distinct_count=100)
        assert _suggest_symbology_type(stats) == "graduated"

    def test_categorical_palette(self) -> None:
        stats = _make_stats(is_categorical=True)
        palette = _suggest_palette(stats)
        assert palette == "material_set1"

    def test_skewed_uses_logarithmic(self) -> None:
        stats = _make_stats(mean=100, median=10)
        method = _suggest_classification_method(stats)
        assert method == "logarithmic"

    def test_normal_uses_quantile(self) -> None:
        stats = _make_stats(mean=50, median=50)
        method = _suggest_classification_method(stats)
        assert method == "quantile"


class TestAutoGenerate(TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="Auto Test",
            db_schema="public",
        )
        self.layer = Layer.objects.create(
            key="auto-layer",
            name="Auto Layer",
            workspace=self.workspace,
            db_table="auto_test_table",
            layer_source="test",
            geometry_type="fill",
        )

    @patch("brewgis.workspace.symbology.auto.classify")
    @patch("brewgis.workspace.symbology.auto.compute_statistics")
    @patch("brewgis.workspace.symbology.auto.list_columns")
    def test_auto_generate_creates_config(
        self,
        mock_list_columns,
        mock_compute_stats,
        mock_classify,
    ) -> None:
        """Auto-generation should create a SymbologyConfig and StyleClasses."""
        mock_list_columns.return_value = [
            {"name": "population", "type": "float8"},
            {"name": "name", "type": "text"},
        ]
        mock_compute_stats.return_value = _make_stats(
            is_categorical=False,
            distinct_count=50,
            min_value=0.0,
            max_value=10000.0,
            mean=5000.0,
            median=4500.0,
            stddev=2000.0,
        )

        mock_classify.return_value = ClassificationResult(
            method="quantile",
            breaks=[0, 2000, 4000, 6000, 8000, 10000],
            labels=["0 - 2000", "2000 - 4000", "4000 - 6000", "6000 - 8000", "8000 - 10000"],
        )
        config = auto_generate_symbology(self.layer, attribute_column="population")

        self.assertIsNotNone(config)
        self.assertEqual(config.layer_id, self.layer.pk)
        self.assertTrue(config.auto_generated)
        self.assertEqual(config.attribute_column, "population")

        # Should have created style classes
        classes = list(config.classes.all())
        self.assertGreater(len(classes), 0)

    @patch("brewgis.workspace.symbology.auto.compute_statistics")
    @patch("brewgis.workspace.symbology.auto.list_columns")
    def test_auto_generate_categorical(
        self,
        mock_list_columns,
        mock_compute_stats,
    ) -> None:
        """Categorical data should produce one class per value."""
        mock_list_columns.return_value = [
            {"name": "category", "type": "text"},
        ]
        mock_compute_stats.return_value = ColumnStatistics(
            column_name="category",
            data_type="text",
            count=100,
            null_count=0,
            distinct_count=5,
            is_categorical=True,
            frequencies={"A": 30, "B": 25, "C": 20, "D": 15, "E": 10},
        )

        config = auto_generate_symbology(self.layer, attribute_column="category")

        self.assertEqual(config.symbology_type, "categorical")
        classes = list(config.classes.all())
        self.assertEqual(len(classes), 5)

    @patch("brewgis.workspace.symbology.auto.classify")
    @patch("brewgis.workspace.symbology.auto.compute_statistics")
    @patch("brewgis.workspace.symbology.auto.list_columns")
    def test_auto_generate_updates_existing(
        self,
        mock_list_columns,
        mock_compute_stats,
        mock_classify,
    ) -> None:
        """Re-running should update existing config."""
        mock_list_columns.return_value = [
            {"name": "val", "type": "float8"},
        ]
        mock_compute_stats.return_value = _make_stats(distinct_count=50)
        mock_classify.return_value = ClassificationResult(
            method="quantile",
            breaks=[0, 2500, 5000, 7500, 10000],
            labels=["0 - 2500", "2500 - 5000", "5000 - 7500", "7500 - 10000"],
        )

        config1 = auto_generate_symbology(self.layer, attribute_column="val")
        first_id = config1.pk

        config2 = auto_generate_symbology(self.layer, attribute_column="val")
        self.assertEqual(config2.pk, first_id)

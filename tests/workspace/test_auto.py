"""Tests for the auto-generation pipeline."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from brewgis.workspace.models import Layer
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace
from brewgis.workspace.symbology.auto import _resolve_palette_name
from brewgis.workspace.symbology.auto import _suggest_classification_method
from brewgis.workspace.symbology.auto import _suggest_palette
from brewgis.workspace.symbology.auto import _suggest_symbology_type
from brewgis.workspace.symbology.auto import auto_generate_symbology
from brewgis.workspace.symbology.auto import resolve_symbology_source
from brewgis.workspace.symbology.classifiers import ClassificationResult
from brewgis.workspace.symbology.stats import ColumnStatistics


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


class TestResolvePaletteName:
    """Palette precedence: caller, then the result table's registered default,
    then the statistics-driven suggestion."""

    def test_explicit_palette_wins(self) -> None:
        """A caller's palette is never overridden by the registry default."""
        stats = _make_stats()
        assert _resolve_palette_name("greens", "vmt", stats) == "greens"

    def test_result_table_default_applies(self) -> None:
        """An analysis result table keeps the palette registered for its metric
        even though the data shape would have suggested something else."""
        stats = _make_stats(is_categorical=False)
        assert _resolve_palette_name(None, "vmt", stats) == "magma"
        assert _suggest_palette(stats) != "magma"

    def test_unknown_table_falls_back_to_suggestion(self) -> None:
        """A layer that is not an analysis result gets a suggested palette."""
        stats = _make_stats(is_categorical=True)
        assert _resolve_palette_name(None, "imported_parcels", stats) == "material_set1"

    def test_suggestion_is_lowercased(self) -> None:
        stats = _make_stats()
        assert _resolve_palette_name("BLUES", "imported_parcels", stats) == "blues"


class TestAutoGenerate(TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="Auto Test",
            db_schema="public",
        )
        # auto_generate_symbology() falls back to the workspace's BASE
        # scenario when none is given — every workspace has one in practice
        # (auto-created at workspace-creation time).
        Scenario.objects.create(
            name="Base Scenario",
            workspace=self.workspace,
            base_year=2020,
            horizon_year=2050,
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
            labels=[
                "0 - 2000",
                "2000 - 4000",
                "4000 - 6000",
                "6000 - 8000",
                "8000 - 10000",
            ],
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
    def test_keeps_the_layers_zero_transparency_setting(
        self,
        mock_list_columns,
        mock_compute_stats,
        mock_classify,
    ) -> None:
        """Re-running auto-generation leaves "Zero Transparent" alone.

        It used to stamp the flag (and the null handling) back to their
        defaults, so clicking Auto silently undid the user's choice — and the
        exclusion of zeros it implies.
        """
        mock_list_columns.return_value = [{"name": "val", "type": "float8"}]
        mock_compute_stats.return_value = _make_stats(distinct_count=50)
        mock_classify.return_value = ClassificationResult(
            method="quantile",
            breaks=[0, 5000, 10000],
            labels=["0 - 5000", "5000 - 10000"],
        )
        config = SymbologyConfig.objects.create(
            layer=self.layer,
            zero_transparent=True,
            null_handling="custom_color",
            null_color="#123456",
        )

        updated = auto_generate_symbology(self.layer, attribute_column="val")

        self.assertEqual(updated.pk, config.pk)
        self.assertTrue(updated.zero_transparent)
        self.assertEqual(updated.null_handling, "custom_color")
        self.assertEqual(updated.null_color, "#123456")
        self.assertTrue(mock_compute_stats.call_args.kwargs["exclude_zero"])
        self.assertTrue(mock_classify.call_args.kwargs["exclude_zero"])

    @patch("brewgis.workspace.symbology.auto.classify")
    @patch("brewgis.workspace.symbology.auto.compute_statistics")
    @patch("brewgis.workspace.symbology.auto.list_columns")
    def test_zero_transparent_excludes_zeros_from_classification(
        self,
        mock_list_columns,
        mock_compute_stats,
        mock_classify,
    ) -> None:
        """Turning it on reaches both the statistics and the classifier."""
        mock_list_columns.return_value = [{"name": "val", "type": "float8"}]
        mock_compute_stats.return_value = _make_stats(distinct_count=50)
        mock_classify.return_value = ClassificationResult(
            method="quantile",
            breaks=[10, 5000, 10000],
            labels=["10 - 5000", "5000 - 10000"],
        )

        config = auto_generate_symbology(
            self.layer, attribute_column="val", zero_transparent=True
        )

        self.assertTrue(config.zero_transparent)
        self.assertTrue(mock_compute_stats.call_args.kwargs["exclude_zero"])
        self.assertTrue(mock_classify.call_args.kwargs["exclude_zero"])

    @patch("brewgis.workspace.symbology.auto.classify")
    @patch("brewgis.workspace.symbology.auto.compute_statistics")
    @patch("brewgis.workspace.symbology.auto.list_columns")
    def test_zeros_stay_in_the_classification_by_default(
        self,
        mock_list_columns,
        mock_compute_stats,
        mock_classify,
    ) -> None:
        mock_list_columns.return_value = [{"name": "val", "type": "float8"}]
        mock_compute_stats.return_value = _make_stats(distinct_count=50)
        mock_classify.return_value = ClassificationResult(
            method="quantile",
            breaks=[0, 5000, 10000],
            labels=["0 - 5000", "5000 - 10000"],
        )

        config = auto_generate_symbology(self.layer, attribute_column="val")

        self.assertFalse(config.zero_transparent)
        self.assertFalse(mock_compute_stats.call_args.kwargs["exclude_zero"])
        self.assertFalse(mock_classify.call_args.kwargs["exclude_zero"])

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


class TestResolveSymbologySource(TestCase):
    """Tests for ``resolve_symbology_source`` — deciding raw table vs canvas view."""

    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="Scenario-Aware Symbology Test",
            db_schema="public",
            base_table="public.base_canvas",
        )
        self.base_layer = Layer.objects.create(
            key="base_canvas",
            name="Base Canvas",
            workspace=self.workspace,
            db_table="base_canvas",
            db_schema="public",
            layer_source="test",
            geometry_type="fill",
        )
        self.other_layer = Layer.objects.create(
            key="zoning",
            name="Zoning",
            workspace=self.workspace,
            db_table="zoning_districts",
            db_schema="public",
            layer_source="test",
            geometry_type="fill",
        )
        self.scenario = Scenario.objects.create(
            name="Test Scenario",
            slug="test-scenario",
            workspace=self.workspace,
            scenario_type=ScenarioType.ALTERNATIVE,
            base_year=2020,
            horizon_year=2050,
        )
        self.base_scenario = Scenario.objects.create(
            name="Base Scenario",
            workspace=self.workspace,
            base_year=2020,
            horizon_year=2050,
        )

    def test_no_scenario_uses_raw_table(self) -> None:
        """A BASE scenario (no paint overlay) resolves to the raw table."""
        schema, table = resolve_symbology_source(self.base_layer, self.base_scenario)
        assert (schema, table) == ("public", "base_canvas")

    def test_base_layer_with_scenario_uses_canvas_view(self) -> None:
        schema, table = resolve_symbology_source(self.base_layer, self.scenario)
        assert schema == self.scenario.target_schema
        assert table == f"scenario_{self.scenario.slug}_canvas"

    def test_non_base_layer_ignores_scenario(self) -> None:
        """A non-paintable layer always reads its own raw table."""
        schema, table = resolve_symbology_source(self.other_layer, self.scenario)
        assert (schema, table) == ("public", "zoning_districts")


class TestAutoGenerateScenarioAware(TestCase):
    """Tests that auto_generate_symbology computes breaks against the
    scenario canvas view (not the raw base table) when scenario is given."""

    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="Scenario-Aware Auto Generate Test",
            db_schema="public",
            base_table="public.base_canvas",
        )
        self.base_layer = Layer.objects.create(
            key="base_canvas",
            name="Base Canvas",
            workspace=self.workspace,
            db_table="base_canvas",
            db_schema="public",
            layer_source="test",
            geometry_type="fill",
        )
        self.scenario = Scenario.objects.create(
            name="Test Scenario",
            slug="test-scenario",
            workspace=self.workspace,
            scenario_type=ScenarioType.ALTERNATIVE,
            base_year=2020,
            horizon_year=2050,
        )
        self.base_scenario = Scenario.objects.create(
            name="Base Scenario",
            workspace=self.workspace,
            base_year=2020,
            horizon_year=2050,
        )

    @patch("brewgis.workspace.symbology.auto.classify")
    @patch("brewgis.workspace.symbology.auto.compute_statistics")
    @patch("brewgis.workspace.symbology.auto.list_columns")
    def test_scenario_routes_stats_through_canvas_view(
        self, mock_list_columns, mock_compute_stats, mock_classify
    ) -> None:
        mock_list_columns.return_value = [{"name": "du", "type": "float8"}]
        mock_compute_stats.return_value = _make_stats(distinct_count=50)
        mock_classify.return_value = ClassificationResult(
            method="quantile",
            breaks=[0, 25, 50, 75, 100],
            labels=["0 - 25", "25 - 50", "50 - 75", "75 - 100"],
        )

        auto_generate_symbology(
            self.base_layer, attribute_column="du", scenario=self.scenario
        )

        mock_compute_stats.assert_called_once_with(
            self.scenario.target_schema,
            f"scenario_{self.scenario.slug}_canvas",
            "du",
            exclude_zero=False,
        )

    @patch("brewgis.workspace.symbology.auto.classify")
    @patch("brewgis.workspace.symbology.auto.compute_statistics")
    @patch("brewgis.workspace.symbology.auto.list_columns")
    def test_no_scenario_routes_stats_through_raw_table(
        self, mock_list_columns, mock_compute_stats, mock_classify
    ) -> None:
        """No scenario given falls back to the workspace's BASE scenario,
        which resolves to the raw table (no paint overlay to COALESCE)."""
        mock_list_columns.return_value = [{"name": "du", "type": "float8"}]
        mock_compute_stats.return_value = _make_stats(distinct_count=50)
        mock_classify.return_value = ClassificationResult(
            method="quantile",
            breaks=[0, 25, 50, 75, 100],
            labels=["0 - 25", "25 - 50", "50 - 75", "75 - 100"],
        )

        auto_generate_symbology(self.base_layer, attribute_column="du")

        mock_compute_stats.assert_called_once_with(
            "public", "base_canvas", "du", exclude_zero=False
        )

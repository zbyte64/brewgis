# ruff: noqa: ARG002
"""Tests for Celery tasks in the analysis pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

from brewgis.workspace.models import DataImportRun
from brewgis.workspace.tasks import export_building_types_task
from brewgis.workspace.tasks import run_census_fetch
from brewgis.workspace.tasks import run_lehd_fetch
from brewgis.workspace.tasks import run_poi_fetch
from brewgis.workspace.tasks import run_spatial_allocation

# ── export_building_types_task ──────────────────────────────────────


class TestExportBuildingTypesTask:
    """Tests for :func:`export_building_types_task`."""

    @patch("brewgis.workspace.tasks.export_building_types")
    def test_success(self, mock_export: MagicMock) -> None:
        """Successful export returns count in result dict."""
        mock_export.return_value = 42

        result = export_building_types_task(schema="test_schema", table="bt")

        assert result == {"success": True, "count": 42, "error": None}
        mock_export.assert_called_once_with(schema="test_schema", table="bt")

    @patch("brewgis.workspace.tasks.export_building_types")
    def test_error(self, mock_export: MagicMock) -> None:
        """Exception during export propagates to the caller."""
        mock_export.side_effect = RuntimeError("DB connection lost")

        try:
            export_building_types_task(schema="public", table="built_forms")
            assert False, "Expected RuntimeError"
        except RuntimeError:
            pass
        mock_export.assert_called_once_with(schema="public", table="built_forms")

    @patch("brewgis.workspace.tasks.export_building_types")
    def test_default_params(self, mock_export: MagicMock) -> None:
        """Default parameters should be used when none are provided."""
        mock_export.return_value = 0

        export_building_types_task()

        mock_export.assert_called_once_with(schema="public", table="built_forms")


# ── run_spatial_allocation ──────────────────────────────────────────


class TestRunSpatialAllocation:
    """Tests for :func:`run_spatial_allocation`."""

    def test_does_not_exist(self) -> None:
        """Missing DataImportRun returns error dict."""
        with patch(
            "brewgis.workspace.tasks.DataImportRun.objects.get",
            side_effect=DataImportRun.DoesNotExist,
        ):
            result = run_spatial_allocation(
                999,
                source_schema="public",
                source_table="src",
                target_schema="public",
                target_table="tgt",
                columns=["pop"],
            )

        assert result == {"success": False, "error": "DataImportRun 999 not found"}

    @patch("brewgis.workspace.tasks.DataImportRun.objects.get")
    @patch("brewgis.workspace.tasks.validate_spatial_allocation")
    def test_success(self, mock_soda: MagicMock, mock_get: MagicMock) -> None:
        """Successful allocation returns success + result keys."""
        mock_soda.return_value = {"success": True, "failures": []}
        run_mock = MagicMock()
        mock_get.return_value = run_mock

        mock_alloc = MagicMock(return_value={"rows_affected": 150})
        with patch("brewgis.workspace.tasks.allocate_attributes", mock_alloc):
            result = run_spatial_allocation(
                1,
                source_schema="public",
                source_table="census_data",
                target_schema="public",
                target_table="parcels",
                columns=["pop", "hh"],
                column_prefix="acs_",
            )

        assert result == {
            "success": True,
            "rows_affected": 150,
            "validation": {"success": True, "failures": []},
        }
        mock_alloc.assert_called_once_with(
            source_schema="public",
            source_table="census_data",
            target_schema="public",
            target_table="parcels",
            columns=["pop", "hh"],
            target_column_prefix="acs_",
            source_geom_col="geom",
            target_geom_col="geom",
        )
        mock_soda.assert_called_once_with(schema="public", table="parcels")
        assert run_mock.status == "completed"
        assert run_mock.result == {
            "rows_affected": 150,
            "validation": {"success": True, "failures": []},
        }
        run_mock.save.assert_called()

    @patch("brewgis.workspace.tasks.DataImportRun.objects.get")
    def test_error_exception(self, mock_get: MagicMock) -> None:
        """Exception during allocation propagates to the caller."""
        run_mock = MagicMock()
        mock_get.return_value = run_mock

        with patch(
            "brewgis.workspace.tasks.allocate_attributes",
            side_effect=ValueError("Invalid geometry"),
        ):
            try:
                run_spatial_allocation(
                    1,
                    source_schema="public",
                    source_table="src",
                    target_schema="public",
                    target_table="tgt",
                    columns=["x"],
                )
                assert False, "Expected ValueError"
            except ValueError:
                pass


# ── run_census_fetch ────────────────────────────────────────────────


class TestRunCensusFetch:
    """Tests for :func:`run_census_fetch`."""

    @patch("brewgis.workspace.tasks.auto_generate_symbology")
    @patch("brewgis.workspace.tasks.DataImportRun.objects.get")
    @patch("brewgis.workspace.tasks.run_census_pipeline")
    @patch("brewgis.workspace.tasks.Layer.objects.get_or_create")
    def test_success(
        self,
        mock_get_or_create: MagicMock,
        mock_dlt_pipeline: MagicMock,
        mock_run_get: MagicMock,
        mock_symbology: MagicMock,
    ) -> None:
        """Successful census fetch returns count."""
        run_mock = MagicMock()
        mock_run_get.return_value = run_mock
        mock_dlt_pipeline.return_value = {
            "success": True,
            "table_name": "public.acs_raw",
            "row_count": 500,
            "load_info": "ok",
        }
        layer_mock = MagicMock(pk=7)
        mock_get_or_create.return_value = (layer_mock, True)

        result = run_census_fetch(
            run_pk=1,
            state_fips="06",
            county_fips="067",
            schema="public",
        )

        assert result == {"success": True, "count": 500}
        assert run_mock.status == "completed"
        assert run_mock.result["row_count"] == 500
        mock_dlt_pipeline.assert_called_once_with("06", "067", 2022, "public")

    @patch("brewgis.workspace.tasks.DataImportRun.objects.get")
    @patch("brewgis.workspace.tasks.run_census_pipeline")
    def test_dlt_failure(
        self,
        mock_dlt_pipeline: MagicMock,
        mock_run_get: MagicMock,
    ) -> None:
        """dlt pipeline failure returns error dict."""
        run_mock = MagicMock()
        mock_run_get.return_value = run_mock
        mock_dlt_pipeline.return_value = {
            "success": False,
            "error": "connection timeout",
        }

        result = run_census_fetch(
            run_pk=1,
            state_fips="06",
            county_fips="067",
            schema="public",
        )

        assert result == {
            "success": False,
            "error": "dlt extraction failed: connection timeout",
        }
        assert run_mock.status == "failed"

    @patch("brewgis.workspace.tasks.DataImportRun.objects.get")
    def test_does_not_exist(self, mock_run_get: MagicMock) -> None:
        """Missing DataImportRun returns error dict."""
        mock_run_get.side_effect = DataImportRun.DoesNotExist

        result = run_census_fetch(
            run_pk=999,
            state_fips="06",
            county_fips="067",
            schema="public",
        )

        assert result == {"success": False, "error": "DataImportRun 999 not found"}


# ── run_lehd_fetch ──────────────────────────────────────────────────


class TestRunLehdFetch:
    """Tests for :func:`run_lehd_fetch`."""

    @patch("brewgis.workspace.tasks.auto_generate_symbology")
    @patch("brewgis.workspace.tasks.DataImportRun.objects.get")
    @patch("brewgis.workspace.tasks.run_lehd_pipeline")
    @patch("brewgis.workspace.tasks.Layer.objects.get_or_create")
    def test_success(
        self,
        mock_get_or_create: MagicMock,
        mock_dlt_pipeline: MagicMock,
        mock_run_get: MagicMock,
        mock_symbology: MagicMock,
    ) -> None:
        """Successful LEHD fetch returns count."""
        run_mock = MagicMock()
        mock_run_get.return_value = run_mock
        mock_dlt_pipeline.return_value = {
            "success": True,
            "table_name": "public.lodes_raw",
            "row_count": 300,
            "load_info": "ok",
        }
        layer_mock = MagicMock(pk=8)
        mock_get_or_create.return_value = (layer_mock, True)

        result = run_lehd_fetch(
            run_pk=2,
            state_fips="06",
            county_fips="067",
            schema="public",
        )

        assert result == {"success": True, "count": 300}
        assert run_mock.status == "completed"
        assert run_mock.result["row_count"] == 300

    @patch("brewgis.workspace.tasks.DataImportRun.objects.get")
    @patch("brewgis.workspace.tasks.run_lehd_pipeline")
    def test_dlt_failure(
        self,
        mock_dlt_pipeline: MagicMock,
        mock_run_get: MagicMock,
    ) -> None:
        """dlt pipeline failure returns error dict."""
        run_mock = MagicMock()
        mock_run_get.return_value = run_mock
        mock_dlt_pipeline.return_value = {
            "success": False,
            "error": "connection timeout",
        }

        result = run_lehd_fetch(
            run_pk=2,
            state_fips="06",
            county_fips="067",
            schema="public",
        )

        assert result == {
            "success": False,
            "error": "dlt extraction failed: connection timeout",
        }
        assert run_mock.status == "failed"

    @patch("brewgis.workspace.tasks.DataImportRun.objects.get")
    def test_does_not_exist(self, mock_run_get: MagicMock) -> None:
        """Missing DataImportRun returns error dict."""
        mock_run_get.side_effect = DataImportRun.DoesNotExist

        result = run_lehd_fetch(
            run_pk=999,
            state_fips="06",
            county_fips="067",
            schema="public",
        )

        assert result == {"success": False, "error": "DataImportRun 999 not found"}


# ── run_poi_fetch ───────────────────────────────────────────────────


class TestRunPoiFetch:
    """Tests for :func:`run_poi_fetch`."""

    @patch("brewgis.workspace.tasks.auto_generate_symbology")
    @patch("brewgis.workspace.tasks.DataImportRun.objects.get")
    @patch("brewgis.workspace.tasks.run_poi_pipeline")
    @patch("brewgis.workspace.tasks.Layer.objects.get_or_create")
    def test_success(
        self,
        mock_get_or_create: MagicMock,
        mock_dlt_pipeline: MagicMock,
        mock_run_get: MagicMock,
        mock_symbology: MagicMock,
    ) -> None:
        """Successful POI fetch returns count."""
        run_mock = MagicMock()
        mock_run_get.return_value = run_mock
        mock_dlt_pipeline.return_value = {
            "success": True,
            "table_name": "public.poi_raw",
            "row_count": 120,
            "load_info": "ok",
        }
        layer_mock = MagicMock(pk=9)
        mock_get_or_create.return_value = (layer_mock, True)

        result = run_poi_fetch(
            run_pk=3,
            min_lng=-122.5,
            min_lat=37.5,
            max_lng=-122.0,
            max_lat=38.0,
            categories=["school", "hospital"],
            schema="public",
        )

        assert result == {"success": True, "count": 120}
        assert run_mock.status == "completed"
        assert run_mock.result["row_count"] == 120

    @patch("brewgis.workspace.tasks.DataImportRun.objects.get")
    @patch("brewgis.workspace.tasks.run_poi_pipeline")
    def test_dlt_failure(
        self,
        mock_dlt_pipeline: MagicMock,
        mock_run_get: MagicMock,
    ) -> None:
        """dlt pipeline failure returns error dict."""
        run_mock = MagicMock()
        mock_run_get.return_value = run_mock
        mock_dlt_pipeline.return_value = {
            "success": False,
            "error": "connection timeout",
        }

        result = run_poi_fetch(
            run_pk=3,
            min_lng=-122.5,
            min_lat=37.5,
            max_lng=-122.0,
            max_lat=38.0,
            categories=None,
            schema="public",
        )

        assert result == {
            "success": False,
            "error": "dlt extraction failed: connection timeout",
        }
        assert run_mock.status == "failed"

    @patch("brewgis.workspace.tasks.DataImportRun.objects.get")
    def test_does_not_exist(self, mock_run_get: MagicMock) -> None:
        """Missing DataImportRun returns error dict."""
        mock_run_get.side_effect = DataImportRun.DoesNotExist

        result = run_poi_fetch(
            run_pk=999,
            min_lng=-122.5,
            min_lat=37.5,
            max_lng=-122.0,
            max_lat=38.0,
            categories=None,
            schema="public",
        )

        assert result == {"success": False, "error": "DataImportRun 999 not found"}

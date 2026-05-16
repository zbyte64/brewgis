"""Tests for the Dagster client service."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from brewgis.workspace.services.dagster_client import submit_impute_run


class TestSubmitImputeRun:
    """Tests for :func:`submit_impute_run`."""

    def test_submit_success_returns_run_id(self) -> None:
        """A successful submission should return the run ID."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.run_id = "dagster-run-001"
        mock_result.message = ""

        with patch("brewgis.workspace.services.dagster_client._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.submit_job_execution.return_value = mock_result
            mock_get.return_value = mock_client

            run_id = submit_impute_run(
                {
                    "source_schema": "public",
                    "source_table": "census_acs",
                    "source_column": "pop",
                    "target_schema": "public",
                    "target_table": "parcels",
                    "target_column": "pop",
                    "scenario_id": "test_001",
                }
            )

            assert run_id == "dagster-run-001"
            mock_client.submit_job_execution.assert_called_once_with(
                job_name="impute_area_proportional",
                repository_location_name="brewgis",
                repository_name="__repository__",
                run_config={
                    "ops": {
                        "impute_area_proportional_asset": {
                            "config": {
                                "source_schema": "public",
                                "source_table": "census_acs",
                                "source_column": "pop",
                                "target_schema": "public",
                                "target_table": "parcels",
                                "target_column": "pop",
                                "scenario_id": "test_001",
                            }
                        }
                    }
                },
            )

    def test_submit_failure_raises_runtime_error(self) -> None:
        """A failed submission should raise RuntimeError."""
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.message = "Job not found"

        with patch("brewgis.workspace.services.dagster_client._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.submit_job_execution.return_value = mock_result
            mock_get.return_value = mock_client

            with pytest.raises(RuntimeError, match="Job not found"):
                submit_impute_run(
                    {
                        "source_schema": "public",
                        "source_table": "census_acs",
                        "source_column": "pop",
                        "target_schema": "public",
                        "target_table": "parcels",
                        "target_column": "pop",
                        "scenario_id": "test_001",
                    }
                )

    def test_submit_missing_run_id_raises_runtime_error(self) -> None:
        """A success with no run_id should raise RuntimeError."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.run_id = None
        mock_result.message = ""

        with patch("brewgis.workspace.services.dagster_client._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.submit_job_execution.return_value = mock_result
            mock_get.return_value = mock_client

            with pytest.raises(RuntimeError, match="no run_id was returned"):
                submit_impute_run(
                    {
                        "source_schema": "public",
                        "source_table": "census_acs",
                        "source_column": "pop",
                        "target_schema": "public",
                        "target_table": "parcels",
                        "target_column": "pop",
                        "scenario_id": "test_001",
                    }
                )

    def test_submit_no_success_no_message(self) -> None:
        """Failure with no message should raise RuntimeError with default."""
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.message = ""

        with patch("brewgis.workspace.services.dagster_client._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.submit_job_execution.return_value = mock_result
            mock_get.return_value = mock_client

            with pytest.raises(RuntimeError, match="unsuccessful result"):
                submit_impute_run(
                    {
                        "source_schema": "public",
                        "source_table": "census_acs",
                        "source_column": "pop",
                        "target_schema": "public",
                        "target_table": "parcels",
                        "target_column": "pop",
                        "scenario_id": "test_001",
                    }
                )

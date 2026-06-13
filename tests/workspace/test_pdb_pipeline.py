"""Tests for Census Planning Database (PDB) dlt pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from brewgis.workspace.dlt_pipelines.pdb import pdb_source
from brewgis.workspace.dlt_pipelines.pdb import run_pdb_pipeline

# Sample API response matching the Census PDB format.
# First row is headers, subsequent rows are data.
_SAMPLE_API_RESPONSE: list[list[str]] = [
    [
        "GIDBG",
        "Tot_Vacant_Units_ACS_18_22",
        "Tot_Housing_Units_ACS_18_22",
        "Tot_Occp_Units_ACS_18_22",
        "Tot_GQ_CEN_2020",
        "Inst_GQ_CEN_2020",
        "Non_Inst_GQ_CEN_2020",
        "Low_Response_Score",
        "pct_Renter_Occp_HU_ACS_18_22",
        "pct_Prs_Blw_Pov_Lev_ACS_18_22",
        "Tot_Population_ACS_18_22",
    ],
    [
        "060670001001",
        "50",
        "500",
        "450",
        "120",
        "80",
        "40",
        "15.3",
        "45.2",
        "12.1",
        "1250",
    ],
    [
        "060670001002",
        "20",
        "400",
        "380",
        "0",
        "0",
        "0",
        "-666666666",
        "60.5",
        "8.7",
        "950",
    ],
    [
        "060670002001",
        "-666666666",
        "350",
        "330",
        "200",
        "150",
        "50",
        "22.8",
        "55.0",
        "18.3",
        "1100",
    ],
]


class TestPDBSource:
    """Tests for the PDB dlt source function."""

    def test_source_returns_list(self) -> None:
        """pdb_source should return a dlt Source with one resource."""
        with (
            patch(
                "brewgis.workspace.dlt_pipelines.pdb.Path.exists",
                return_value=False,
            ),
            patch(
                "brewgis.workspace.dlt_pipelines.pdb.requests.get",
            ) as mock_get,
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = _SAMPLE_API_RESPONSE
            mock_response.content = b"{}"
            mock_get.return_value = mock_response

            source = pdb_source("06", "067")
        assert len(source.resources) == 1
        assert "pdb_raw" in source.resources

    def test_source_yields_records(self) -> None:
        """Should yield records with correct shape and numeric types."""
        with (
            patch(
                "brewgis.workspace.dlt_pipelines.pdb.Path.exists",
                return_value=False,
            ),
            patch(
                "brewgis.workspace.dlt_pipelines.pdb.requests.get",
            ) as mock_get,
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = _SAMPLE_API_RESPONSE
            mock_response.content = b"{}"
            mock_get.return_value = mock_response

            source = pdb_source("06", "067")
            records = list(source.resources["pdb_raw"])

        assert len(records) == 3

        # First record — normal values
        r0 = records[0]
        assert r0["gidbg"] == "060670001001"
        assert r0["state"] == "06"
        assert r0["county"] == "067"
        assert r0["data_year"] == 2024
        assert r0["tot_vacant_units_acs_18_22"] == 50
        assert r0["tot_housing_units_acs_18_22"] == 500
        assert r0["tot_gq_cen_2020"] == 120
        assert r0["low_response_score"] == 15.3
        assert r0["pct_renter_occp_hu_acs_18_22"] == 45.2
        assert r0["pct_prs_blw_pov_lev_acs_18_22"] == 12.1

        # Second record — has sentinel for low_response_score
        r1 = records[1]
        assert r1["gidbg"] == "060670001002"
        assert r1["low_response_score"] is None  # -666666666 sentinel
        assert r1["pct_renter_occp_hu_acs_18_22"] == 60.5
        assert r1["tot_gq_cen_2020"] == 0

        # Third record — has sentinel for vacant units
        r2 = records[2]
        assert r2["gidbg"] == "060670002001"
        assert r2["tot_vacant_units_acs_18_22"] is None  # -666666666 sentinel
        assert r2["low_response_score"] == 22.8

    def test_source_uses_cache(self) -> None:
        """Should read from cache file when available and ignore_cache=False."""
        with (
            patch(
                "brewgis.workspace.dlt_pipelines.pdb.Path.exists",
                return_value=True,
            ),
            patch(
                "brewgis.workspace.dlt_pipelines.pdb.json.load",
            ) as mock_json_load,
            patch(
                "brewgis.workspace.dlt_pipelines.pdb.Path.open",
            ) as mock_open,
        ):
            mock_json_load.return_value = _SAMPLE_API_RESPONSE
            mock_fh = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_fh

            source = pdb_source("06", "067", ignore_cache=False)
            records = list(source.resources["pdb_raw"])

        assert len(records) == 3
        assert records[0]["gidbg"] == "060670001001"
        mock_json_load.assert_called_once()

    def test_source_ignore_cache(self) -> None:
        """Should fetch from API when ignore_cache=True."""
        with (
            patch(
                "brewgis.workspace.dlt_pipelines.pdb.Path.exists",
                return_value=True,
            ),
            patch(
                "brewgis.workspace.dlt_pipelines.pdb.requests.get",
            ) as mock_get,
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = _SAMPLE_API_RESPONSE
            mock_response.content = b"{}"
            mock_get.return_value = mock_response

            source = pdb_source("06", "067", ignore_cache=True)
            records = list(source.resources["pdb_raw"])

        assert len(records) == 3
        mock_get.assert_called_once()


class TestPDBPipeline:
    """Tests for run_pdb_pipeline convenience function."""

    def test_run_pipeline_success(self) -> None:
        """run_pdb_pipeline should return success dict on success."""
        with (
            patch("brewgis.workspace.dlt_pipelines.pdb.dlt.pipeline") as mock_pipeline,
            patch(
                "brewgis.workspace.dlt_pipelines.pdb.get_engine",
            ) as mock_engine,
        ):
            mock_pipe = mock_pipeline.return_value
            mock_pipe.run.return_value = MagicMock()
            mock_pipe.run.return_value.packages = []
            mock_step = MagicMock()
            mock_step.step_info = MagicMock()
            mock_step.step_info.row_counts = {"pdb_raw": 5}
            mock_pipe.last_trace.steps = [mock_step]
            mock_conn = MagicMock()
            mock_engine.return_value.begin.return_value.__enter__.return_value = (
                mock_conn
            )
            result = run_pdb_pipeline("06", "067")
        assert "table_name" in result
        assert result["row_count"] == 5

    def test_run_pipeline_error(self) -> None:
        """run_pdb_pipeline should propagate on failure."""
        with (
            patch("brewgis.workspace.dlt_pipelines.pdb.dlt.pipeline") as mock_pipeline,
            patch(
                "brewgis.workspace.dlt_pipelines.pdb.get_engine",
            ),
        ):
            mock_pipe = mock_pipeline.return_value
            mock_pipe.run.side_effect = RuntimeError("Download failed")
            with pytest.raises(RuntimeError, match="Download failed"):
                run_pdb_pipeline("06", "067")

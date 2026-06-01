"""Tests for TIGER/Line shapefile dlt pipelines."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

from brewgis.workspace.dlt_pipelines.tiger_bg import run_tiger_bg_pipeline
from brewgis.workspace.dlt_pipelines.tiger_bg import tiger_bg_source
from brewgis.workspace.dlt_pipelines.tiger_block import run_tiger_block_pipeline
from brewgis.workspace.dlt_pipelines.tiger_block import tiger_block_source


class TestTigerBGPipeline:
    """Tests for TIGER/Line block group pipeline."""

    def test_source_returns_list(self) -> None:
        """tiger_bg_source should return a dlt Source with one resource."""
        result = tiger_bg_source("06")
        assert result.name == "tiger_bg"

    def test_run_pipeline_success(self) -> None:
        """run_tiger_bg_pipeline should return success dict."""
        with patch(
            "brewgis.workspace.dlt_pipelines.tiger_bg.dlt.pipeline"
        ) as mock_pipeline:
            mock_pipe = mock_pipeline.return_value
            mock_pipe.run.return_value = MagicMock()
            mock_pipe.run.return_value.packages = []
            mock_step = MagicMock()
            mock_step.step_info = MagicMock()
            mock_step.step_info.row_counts = {"tiger_block_groups": 5}
            mock_pipe.last_trace.steps = [mock_step]
            result = run_tiger_bg_pipeline("06")
        assert "table_name" in result
        assert result["row_count"] == 5

    def test_run_pipeline_error(self) -> None:
        """run_tiger_bg_pipeline should propagate on failure."""
        with patch(
            "brewgis.workspace.dlt_pipelines.tiger_bg.dlt.pipeline"
        ) as mock_pipeline:
            mock_pipe = mock_pipeline.return_value
            mock_pipe.run.side_effect = RuntimeError("Download failed")
            try:
                run_tiger_bg_pipeline("06")
                assert False, "Expected RuntimeError"
            except RuntimeError:
                pass


class TestTigerBlockPipeline:
    """Tests for TIGER/Line tabblock pipeline."""

    def test_source_returns_list(self) -> None:
        """tiger_block_source should return a dlt Source with one resource."""
        result = tiger_block_source("06")
        assert result.name == "tiger_block"

    def test_run_pipeline_success(self) -> None:
        """run_tiger_block_pipeline should return success dict."""
        with patch(
            "brewgis.workspace.dlt_pipelines.tiger_block.dlt.pipeline"
        ) as mock_pipeline:
            mock_pipe = mock_pipeline.return_value
            mock_pipe.run.return_value = MagicMock()
            mock_pipe.run.return_value.packages = []
            mock_step = MagicMock()
            mock_step.step_info = MagicMock()
            mock_step.step_info.row_counts = {"tiger_blocks": 5}
            mock_pipe.last_trace.steps = [mock_step]
            result = run_tiger_block_pipeline("06")
        assert "table_name" in result

    def test_run_pipeline_error(self) -> None:
        """run_tiger_block_pipeline should propagate on failure."""
        with patch(
            "brewgis.workspace.dlt_pipelines.tiger_block.dlt.pipeline"
        ) as mock_pipeline:
            mock_pipe = mock_pipeline.return_value
            mock_pipe.run.side_effect = RuntimeError("Download failed")
            try:
                run_tiger_block_pipeline("06")
                assert False, "Expected RuntimeError"
            except RuntimeError:
                pass

"""Tests for Dagster imputation assets."""

from __future__ import annotations


class TestImputeAreaProportionalConfig:
    """Tests for :class:`ImputeAreaProportionalConfig`."""

    def test_config_instantiation(self) -> None:
        """Config should accept all required fields with defaults."""
        from brewgis.workspace.dagster.configs import ImputeAreaProportionalConfig

        config = ImputeAreaProportionalConfig(
            source_schema="src",
            source_table="src_tbl",
            source_column="val",
            target_schema="tgt",
            target_table="tgt_tbl",
            target_column="val",
            scenario_id="test_001",
        )
        assert config.source_schema == "src"
        assert config.source_table == "src_tbl"
        assert config.source_column == "val"
        assert config.target_schema == "tgt"
        assert config.target_table == "tgt_tbl"
        assert config.target_column == "val"
        assert config.scenario_id == "test_001"
        assert config.source_geom_col == "geom"  # default
        assert config.target_geom_col == "geom"  # default


class TestImputeAreaProportionalAsset:
    """Tests for the ``impute_area_proportional_asset`` asset definition."""

    def test_asset_importable(self) -> None:
        """The asset function should be importable."""
        from brewgis.workspace.dagster.assets.impute_assets import (
            impute_area_proportional_asset,
        )

        assert callable(impute_area_proportional_asset)

    def test_asset_keys(self) -> None:
        """The asset should expose its asset keys."""
        from brewgis.workspace.dagster.assets.impute_assets import (
            impute_area_proportional_asset,
        )

        keys = list(impute_area_proportional_asset.keys)
        assert len(keys) >= 1
        assert "impute_area_proportional_asset" in str(keys[0])


class TestImputeJob:
    """Tests for the Dagster job definition."""

    def test_job_importable(self) -> None:
        """The job should be importable and callable."""
        from brewgis.workspace.dagster.jobs.impute_jobs import (
            impute_area_proportional_job,
        )

        assert callable(impute_area_proportional_job)

    def test_job_name(self) -> None:
        """The job should have the expected name."""
        from brewgis.workspace.dagster.jobs.impute_jobs import (
            impute_area_proportional_job,
        )

        assert impute_area_proportional_job.name == "impute_area_proportional"

"""Tests for Soda Core contract files."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


import pytest
import yaml

from brewgis.soda import _empty_result
from brewgis.soda import _soda_dir
from brewgis.soda import run_scan


def _all_contracts() -> list[Path]:
    """Return paths to every contract YAML file (excluding dbt_module_run)."""
    contracts_dir = _soda_dir() / "contracts"
    return sorted(p for p in contracts_dir.glob("*.yml") if p.stem != "dbt_module_run")


class TestContractDiscovery:
    """Contract files exist and are valid YAML."""

    @pytest.mark.models
    def test_contracts_directory_exists(self) -> None:
        contracts_dir = _soda_dir() / "contracts"
        assert contracts_dir.is_dir()

    @pytest.mark.models
    def test_expected_contracts_present(self) -> None:
        names = {p.stem for p in _all_contracts()}
        expected = {
            "base_canvas",
            "census_acs",
            "lehd",
            "poi",
            "nlcd",
            "synthetic_parcels",
            "spatial_allocation",
            "column_stitching",
            "built_form_export",
        }
        missing = expected - names
        extra = names - expected
        assert not missing, f"Missing contracts: {missing}"
        assert not extra, f"Unexpected contracts: {extra}"

    @pytest.mark.models
    def test_all_contracts_parse_as_valid_yaml(self) -> None:
        for path in _all_contracts():
            raw = path.read_text(encoding="utf-8")
            try:
                data = yaml.safe_load(raw)
            except yaml.YAMLError as exc:
                pytest.fail(f"{path.name} is not valid YAML: {exc}")
            assert data is not None, f"{path.name} is empty"
            assert "dataset: __DATASET__" in raw, (
                f"{path.name} is missing 'dataset: __DATASET__' (expected v4 format)"
            )
            assert "columns:" in raw, f"{path.name} is missing 'columns:' section"
            assert "checks:" in raw, f"{path.name} is missing 'checks:'"


class TestRunScan:
    """Tests for the run_scan function (no-database cases)."""

    @pytest.mark.models
    def test_missing_contract_returns_empty_result(self) -> None:
        result = run_scan("nonexistent_contract")
        assert result["success"] is True
        assert result["failures"] == []
        assert result["checkpoint"] == "nonexistent_contract"

    @pytest.mark.models
    def test_empty_result_shape(self) -> None:
        result = _empty_result("test_contract")
        expected_keys = {"success", "checkpoint", "failures", "results_url", "severity"}
        assert set(result.keys()) == expected_keys
        assert result["success"] is True

        assert result["failures"] == []
        assert result["results_url"] is None
        assert result["severity"] is None
        assert result["checkpoint"] == "test_contract"

"""Tests for Phase 1a: Source Column Mapping Configuration."""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.test import TestCase

from brewgis.workspace.analysis.module_registry import CANONICAL_COLUMN_NAMES
from brewgis.workspace.analysis.module_registry import get_column_mapping_vars
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace


class TestGetColumnMappingVars:
    """Tests for get_column_mapping_vars() — a pure function, no DB needed."""

    def test_valid_mapping(self):
        mapping = {"pop": "population", "hh": "households", "du": "dwelling_units"}
        result = get_column_mapping_vars(mapping)
        assert result["canonical_pop"] == "population"
        assert result["canonical_hh"] == "households"
        assert result["canonical_du"] == "dwelling_units"

    def test_partial_mapping(self):
        """Partial mapping only produces vars for specified columns."""
        mapping = {"pop": "population"}
        result = get_column_mapping_vars(mapping)
        assert "canonical_pop" in result
        assert "canonical_hh" not in result

    def test_empty_mapping(self):
        assert get_column_mapping_vars({}) == {}

    def test_unknown_key_ignored(self):
        mapping = {"pop": "population", "nonexistent_column": "nope"}
        result = get_column_mapping_vars(mapping)
        assert "canonical_pop" in result
        assert "canonical_nonexistent_column" not in result

    def test_case_insensitive(self):
        mapping = {"POP": " population_value ", "HH ": "households"}
        result = get_column_mapping_vars(mapping)
        assert "canonical_pop" in result
        assert "canonical_hh" in result

    def test_all_canonical_names(self):
        """Test that all CANONICAL_COLUMN_NAMES can be mapped."""
        mapping = {name: f"source_{name}" for name in CANONICAL_COLUMN_NAMES}
        result = get_column_mapping_vars(mapping)
        for name in CANONICAL_COLUMN_NAMES:
            assert f"canonical_{name}" in result
            assert result[f"canonical_{name}"] == f"source_{name}"


def test_dbt_runner_expands_column_mapping(tmp_path):
    """Test that DbtRunnerWrapper.run() expands column_mapping into canonical vars."""
    pytest.importorskip("dbt")
    from brewgis.workspace.analysis.dbt_runner import DbtRunnerWrapper

    # Create a minimal dbt project so the exists() check passes
    project_dir = tmp_path / "dbt_project"
    project_dir.mkdir()
    dbt_project_yml = project_dir / "dbt_project.yml"
    dbt_project_yml.write_text(
        "name: 'test'\nversion: '1.0.0'\nconfig-version: 2\nprofile: 'test'\n"
    )

    runner = DbtRunnerWrapper(project_dir=str(project_dir))

    with patch("dbt.cli.main.dbtRunner") as MockDbtRunner:
        mock_instance = MockDbtRunner.return_value
        mock_result = MagicMock()
        mock_result.result = None  # triggers _parse_results fallback, avoids iteration
        mock_instance.invoke.return_value = mock_result

        runner.run(
            select=["core"],
            vars_={
                "target_year": 2050,
                "column_mapping": {"pop": "population", "hh": "households"},
            },
        )

    # Capture the args list that was passed to dbtRunner.invoke()
    call_args = mock_instance.invoke.call_args[0][0]
    var_idx = call_args.index("--vars")
    vars_json = json.loads(call_args[var_idx + 1])

    assert vars_json["canonical_pop"] == "population"
    assert vars_json["canonical_hh"] == "households"
    assert "column_mapping" not in vars_json
    assert vars_json["target_year"] == 2050


class TestAnalysisRunColumnMapping(TestCase):
    """Tests for AnalysisRun model's column_mapping field."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test")
        self.scenario = Scenario.objects.create(
            name="Test",
            slug="test",
            workspace=self.workspace,
            base_year=2020,
            horizon_year=2050,
        )

    def test_column_mapping_default_is_empty_dict(self):
        run = AnalysisRun.objects.create(
            workspace=self.workspace,
            scenario=self.scenario,
            modules=["core"],
        )
        assert run.column_mapping == {}

    def test_column_mapping_stores_provided_mapping(self):
        mapping = {"pop": "population", "hh": "households"}
        run = AnalysisRun.objects.create(
            workspace=self.workspace,
            scenario=self.scenario,
            modules=["core"],
            column_mapping=mapping,
        )
        assert run.column_mapping == mapping

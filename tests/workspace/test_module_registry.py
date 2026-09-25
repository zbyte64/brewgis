"""Tests for the analysis module registry — pure function tests.

These tests verify module ordering, result table name resolution,
label lookup, and variable injection without requiring a database.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from brewgis.workspace.analysis.module_registry import MODULE_DEPENDENCIES
from brewgis.workspace.analysis.module_registry import MODULE_RESULT_TABLES
from brewgis.workspace.analysis.module_registry import MODULE_SQLMESH_SELECTORS
from brewgis.workspace.analysis.module_registry import TABLE_PALETTE
from brewgis.workspace.analysis.module_registry import TABLE_PRIMARY_COLUMN
from brewgis.workspace.analysis.module_registry import get_default_palette
from brewgis.workspace.analysis.module_registry import get_module_label
from brewgis.workspace.analysis.module_registry import get_result_table_names
from brewgis.workspace.analysis.module_registry import get_vars_for_module
from brewgis.workspace.analysis.module_registry import model_fqn
from brewgis.workspace.analysis.module_registry import resolve_module_order
from brewgis.workspace.palettes import PALETTES
from brewgis.workspace.palettes import get_diverging_names


class TestResolveModuleOrder:
    """Tests for ``resolve_module_order`` — dependency resolution."""

    def test_single_module_no_deps(self) -> None:
        """A standalone module with no dependencies resolves to itself."""
        result = resolve_module_order(["env_constraint"])
        assert result == ["env_constraint"]

    def test_module_with_dep_prepended(self) -> None:
        """A module's dependency is automatically prepended when missing."""
        result = resolve_module_order(["core"])
        assert result == ["env_constraint", "core"]

    def test_modules_in_correct_order(self) -> None:
        """Full transitive dependency chain is resolved."""
        result = resolve_module_order(["vmt"])
        # vmt -> mode_choice -> trip_distribution -> trip_generation -> core -> env_constraint
        assert result == [
            "env_constraint",
            "core",
            "trip_generation",
            "trip_distribution",
            "mode_choice",
            "vmt",
        ]

    def test_explicit_dep_module_skipped_when_already_seen(self) -> None:
        """When a dependency is already listed explicitly, it is not duplicated."""
        result = resolve_module_order(["env_constraint", "core"])
        assert result == ["env_constraint", "core"]

    def test_multiple_modules_in_dependency_order(self) -> None:
        """Multiple requested modules have their full transitive deps prepended."""
        result = resolve_module_order(["water_demand", "energy_demand"])
        # Both depend on core, which depends on env_constraint
        assert result == ["env_constraint", "core", "water_demand", "energy_demand"]

    def test_interleaved_chain(self) -> None:
        """Full transitive chain for each requested module is resolved."""
        result = resolve_module_order(["vmt", "land_consumption"])
        # vmt -> mode_choice -> trip_distribution -> trip_generation -> core -> env_constraint
        # land_consumption -> core -> env_constraint (already seen)
        assert result == [
            "env_constraint",
            "core",
            "trip_generation",
            "trip_distribution",
            "mode_choice",
            "vmt",
            "land_consumption",
        ]

    def test_unknown_module_raises_value_error(self) -> None:
        """Passing a module name not in the registry raises ValueError."""
        with pytest.raises(ValueError, match="Unknown modules"):
            resolve_module_order(["nonexistent_module"])

    def test_unknown_module_among_known_raises_value_error(self) -> None:
        """A mix of known and unknown modules still raises ValueError."""
        with pytest.raises(ValueError, match="Unknown modules"):
            resolve_module_order(["core", "bogus_module"])

    def test_empty_list_returns_empty_list(self) -> None:
        """An empty list of modules returns an empty list."""
        result = resolve_module_order([])
        assert result == []


class TestResolveModuleOrderCircularDependency:
    """Tests for circular dependency detection (expected failures).

    ``resolve_module_order`` currently does **not** detect cycles.  These tests
    document the expected behavior once cycle detection is added.
    """

    @pytest.mark.xfail(
        strict=True,
        reason="cycle detection not yet implemented in resolve_module_order",
    )
    def test_circular_dependency_raises_value_error(self) -> None:
        """A self-referencing module should raise ValueError."""
        fake_deps: dict[str, list[str]] = dict(MODULE_DEPENDENCIES)
        fake_deps["env_constraint"] = ["env_constraint"]
        with (
            patch.dict(
                "brewgis.workspace.analysis.module_registry.MODULE_DEPENDENCIES",
                fake_deps,
                clear=False,
            ),
            pytest.raises(ValueError, match="circular"),
        ):
            resolve_module_order(["env_constraint"])

    @pytest.mark.xfail(
        strict=True,
        reason="cycle detection not yet implemented in resolve_module_order",
    )
    def test_transitive_cycle_raises_value_error(self) -> None:
        """A transitive dependency cycle should raise ValueError."""
        fake_deps: dict[str, list[str]] = dict(MODULE_DEPENDENCIES)
        fake_deps["vmt"] = ["mode_choice"]
        fake_deps["mode_choice"] = ["vmt"]
        with (
            patch.dict(
                "brewgis.workspace.analysis.module_registry.MODULE_DEPENDENCIES",
                fake_deps,
                clear=False,
            ),
            pytest.raises(ValueError, match="circular"),
        ):
            resolve_module_order(["vmt"])


class TestGetDefaultPalette:
    """Tests for ``get_default_palette`` — the registered palette per result table."""

    def test_every_primary_column_table_has_a_palette(self) -> None:
        """A result layer's palette is only useful if every result table has
        one: these are the layers a run registers, and a missing entry would
        leave that layer on the blank "Manual" palette."""
        missing = set(TABLE_PRIMARY_COLUMN) - set(TABLE_PALETTE)
        assert not missing, f"result tables with no default palette: {missing}"

    def test_every_palette_is_in_the_registry(self) -> None:
        """A default palette must be a palette the editor can render."""
        unknown = set(TABLE_PALETTE.values()) - set(PALETTES)
        assert not unknown, f"palettes not in the registry: {unknown}"

    def test_palettes_differ_across_tables(self) -> None:
        """Analysis layers are stacked on one map, so the defaults must not
        collapse onto a single palette (they used to be indistinguishable)."""
        assert len(set(TABLE_PALETTE.values())) >= 12

    def test_signed_metrics_use_a_diverging_palette(self) -> None:
        """Metrics that read either side of zero diverge around it."""
        diverging = set(get_diverging_names())
        for table in ("core_increment", "agriculture", "fiscal_net_impact"):
            assert get_default_palette(table) in diverging, table

    def test_known_table_returns_its_palette(self) -> None:
        assert get_default_palette("water_demand") == "blues"

    def test_unknown_table_returns_none(self) -> None:
        """An unknown table falls back to the statistics-driven suggestion."""
        assert get_default_palette("not_a_result_table") is None


class TestGetResultTableNames:
    """Tests for ``get_result_table_names`` — result view locations."""

    def test_known_module_returns_qualified_names(self) -> None:
        """A module's tables are its result views in the scenario's result schema."""
        result = get_result_table_names("core", scenario_id="42")
        assert result == [
            "analysis__scenario_42.core_end_state",
            "analysis__scenario_42.core_increment",
        ]

    def test_env_constraint_returns_single_table(self) -> None:
        """env_constraint has a single result table."""
        result = get_result_table_names("env_constraint", scenario_id="99")
        assert result == ["analysis__scenario_99.env_constraint"]

    def test_land_consumption_returns_single_table(self) -> None:
        """land_consumption's only result view is its own model's."""
        result = get_result_table_names("land_consumption", scenario_id="abc")
        assert result == ["analysis__scenario_abc.land_consumption"]

    def test_fiscal_returns_four_tables(self) -> None:
        """fiscal has four result tables."""
        result = get_result_table_names("fiscal", scenario_id="1")
        assert result == [
            "analysis__scenario_1.fiscal_property_tax",
            "analysis__scenario_1.fiscal_sales_tax",
            "analysis__scenario_1.fiscal_service_costs",
            "analysis__scenario_1.fiscal_net_impact",
        ]

    def test_every_result_view_is_published_by_a_model(self) -> None:
        """A module's result tables are exactly its own models.

        The views a scenario reads are published by the scenario's models (see
        ``sqlmesh/macros/analysis_blueprints.py``), so a module can only have a
        result table for a model it actually has — and must list every one of
        them (``env_constraint`` is deliberately absent: it is a Django-side
        step with no SQL model of its own).
        """
        for module, selectors in MODULE_SQLMESH_SELECTORS.items():
            assert MODULE_RESULT_TABLES[module] == selectors, module

    def test_unknown_module_returns_empty_list(self) -> None:
        """An unknown module returns an empty list."""
        result = get_result_table_names("nonexistent", scenario_id="1")
        assert result == []


class TestModelFqn:
    """Tests for ``model_fqn`` — the per-scenario model name scheme."""

    def test_qualifies_with_the_scenario_schema(self) -> None:
        """A model FQN names the scenario's own instance of that model."""
        assert model_fqn("core_end_state", 42) == "brewgis.ascn42.core_end_state"


class TestGetModuleLabel:
    """Tests for ``get_module_label`` — human-readable label lookup."""

    def test_known_module_returns_label(self) -> None:
        """A known module returns its predefined human-readable label."""
        assert get_module_label("core") == "Core Scenario Builder"

    def test_env_constraint_label(self) -> None:
        """env_constraint has a multi-word label."""
        assert get_module_label("env_constraint") == "Environmental Constraint"

    def test_vmt_label(self) -> None:
        """vmt has an uppercase abbreviation label."""
        assert get_module_label("vmt") == "VMT"

    def test_unknown_module_returns_title_cased_name(self) -> None:
        """An unknown module's name is title-cased as a fallback."""
        assert get_module_label("custom_module") == "Custom Module"

    def test_unknown_single_word(self) -> None:
        """A single-word unknown module title-cases correctly."""
        assert get_module_label("results") == "Results"

    def test_unknown_with_underscores(self) -> None:
        """Underscores in unknown module names are replaced with spaces."""
        assert get_module_label("some_long_name") == "Some Long Name"


class TestGetVarsForModule:
    """Tests for ``get_vars_for_module`` — variable dict preparation."""

    def test_inherits_global_vars(self) -> None:
        """The returned dict inherits all keys from the base vars."""
        base = {"scenario_id": "42", "target_schema": "public", "target_year": 2050}
        result = get_vars_for_module("water_demand", base)
        assert result["scenario_id"] == "42"
        assert result["target_schema"] == "public"
        assert result["target_year"] == 2050

    def test_does_not_mutate_base_vars(self) -> None:
        """The original base_vars dict is not modified."""
        base = {"scenario_id": "42"}
        get_vars_for_module("core", base)
        assert "constraints_output" not in base

    def test_core_with_env_constraint_completed(self) -> None:
        """core module injects constraints_output when env_constraint is completed."""
        base = {
            "scenario_id": "99",
            "target_schema": "my_schema",
            "completed_modules": ["env_constraint"],
        }
        result = get_vars_for_module("core", base)
        assert result["constraints_output"] == "my_schema.env_constraint_99"

    def test_core_without_env_constraint_no_injection(self) -> None:
        """core module does NOT inject constraints_output when env_constraint is absent."""
        base = {"scenario_id": "42", "target_schema": "public", "completed_modules": []}
        result = get_vars_for_module("core", base)
        assert "constraints_output" not in result

    def test_core_without_completed_modules_key_no_injection(self) -> None:
        """core module does NOT inject when completed_modules key is missing."""
        base = {"scenario_id": "1", "target_schema": "public"}
        result = get_vars_for_module("core", base)
        assert "constraints_output" not in result

    def test_non_core_module_no_injection(self) -> None:
        """A non-core module does not get constraints_output injected."""
        base = {
            "scenario_id": "42",
            "target_schema": "public",
            "completed_modules": ["env_constraint"],
        }
        result = get_vars_for_module("water_demand", base)
        assert "constraints_output" not in result

    def test_core_default_scenario_id(self) -> None:
        """If scenario_id is missing, 'default' is used as fallback."""
        base = {
            "target_schema": "public",
            "completed_modules": ["env_constraint"],
        }
        result = get_vars_for_module("core", base)
        assert result["constraints_output"] == "public.env_constraint_default"

    def test_core_default_schema(self) -> None:
        """If target_schema is missing, 'public' is used as fallback."""
        base = {"scenario_id": "7", "completed_modules": ["env_constraint"]}
        result = get_vars_for_module("core", base)
        assert result["constraints_output"] == "public.env_constraint_7"

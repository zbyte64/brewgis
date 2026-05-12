"""Shared module registry — single source of truth for analysis module metadata.

Used by both ``pipeline.py`` (orchestration) and ``tasks.py`` (Celery dispatch)
to avoid duplicated MODULE_DEPENDENCIES, MODULE_RESULT_TABLES, and related mappings.
"""

from __future__ import annotations

import warnings
from typing import Any

# Module dependency graph: later modules depend on earlier ones
MODULE_DEPENDENCIES: dict[str, list[str]] = {
    "env_constraint": [],
    "core": ["env_constraint"],
    "displacement_risk": ["core", "acs_equity"],
    "water_demand": ["core"],
    "energy_demand": ["core"],
    "land_consumption": ["core"],
    "fiscal": ["core"],
    "agriculture": ["core"],
    "trip_generation": ["core"],
    "trip_distribution": ["trip_generation"],
    "mode_choice": ["trip_distribution"],
    "vmt": ["mode_choice"],
    "internal_capture": ["trip_distribution"],
    "transport_ghg": ["vmt"],
    "building_water_ghg": ["energy_demand", "water_demand"],
    "total_ghg": ["transport_ghg", "building_water_ghg"],
    "physical_activity": ["mode_choice", "trip_distribution"],
    "health_impacts": ["physical_activity", "transport_ghg"],
    "stormwater_runoff": ["land_consumption"],
    "food_access": ["core"],
    "acs_equity": [],
    "housing_cost_burden": ["core", "acs_equity"],
    "sprawl_index": ["core"],
    "tree_canopy": ["core"],
    "vmt_fee": ["vmt"],
    "displacement_risk_dynamic": ["displacement_risk", "acs_equity"],
    "scenario_summary": [
        "core",
        "vmt",
        "transport_ghg",
        "total_ghg",
        "health_impacts",
        "housing_cost_burden",
        "sprawl_index",
        "water_demand",
        "energy_demand",
        "land_consumption",
    ],
    "sprawl_cost": ["core", "fiscal"],
}


# Module → result table name templates (formatted with scenario_id)
MODULE_RESULT_TABLES: dict[str, list[str]] = {
    "env_constraint": ["env_constraint_{scenario_id}"],
    "core": ["end_state_{scenario_id}", "increment_{scenario_id}"],
    "displacement_risk": ["displacement_risk_{scenario_id}"],
    "water_demand": ["water_demand_{scenario_id}"],
    "energy_demand": ["energy_demand_{scenario_id}"],
    "land_consumption": [
        "land_consumption_{scenario_id}",
        "impervious_surface_{scenario_id}",
    ],
    "fiscal": [
        "fiscal_property_tax_{scenario_id}",
        "fiscal_sales_tax_{scenario_id}",
        "fiscal_service_costs_{scenario_id}",
        "fiscal_net_impact_{scenario_id}",
    ],
    "agriculture": ["agriculture_{scenario_id}"],
    "trip_generation": ["trip_generation_{scenario_id}"],
    "trip_distribution": ["trip_distribution_{scenario_id}"],
    "mode_choice": ["mode_choice_{scenario_id}"],
    "vmt": ["vmt_{scenario_id}"],
    "internal_capture": ["internal_capture_{scenario_id}"],
    "transport_ghg": ["transport_ghg_{scenario_id}"],
    "building_water_ghg": ["building_water_ghg_{scenario_id}"],
    "total_ghg": ["total_ghg_{scenario_id}"],
    "physical_activity": ["physical_activity_{scenario_id}"],
    "health_impacts": ["health_impacts_{scenario_id}"],
    "stormwater_runoff": ["stormwater_runoff_{scenario_id}"],
    "food_access": ["food_access_{scenario_id}"],
    "acs_equity": [],
    "housing_cost_burden": ["housing_cost_burden_{scenario_id}"],
    "sprawl_index": ["sprawl_index_{scenario_id}"],
    "tree_canopy": ["tree_canopy_{scenario_id}"],
    "vmt_fee": ["vmt_fee_{scenario_id}"],
    "displacement_risk_dynamic": ["displacement_risk_dynamic_{scenario_id}"],
    "scenario_summary": ["scenario_summary_{scenario_id}"],
    "sprawl_cost": ["sprawl_cost_{scenario_id}"],
}


# Module → dbt select pattern (list of model names to run)
MODULE_DBT_SELECT: dict[str, list[str]] = {
    "env_constraint": ["env_constraint"],
    "core": ["core_end_state", "core_increment"],
    "water_demand": ["water_demand"],
    "displacement_risk": ["displacement_risk"],
    "energy_demand": ["energy_demand"],
    "land_consumption": ["land_consumption"],
    "fiscal": [
        "fiscal_property_tax",
        "fiscal_sales_tax",
        "fiscal_service_costs",
        "fiscal_net_impact",
    ],
    "agriculture": ["agriculture"],
    "trip_generation": ["trip_generation"],
    "trip_distribution": ["trip_distribution"],
    "mode_choice": ["mode_choice"],
    "vmt": ["vmt"],
    "internal_capture": ["internal_capture"],
    "transport_ghg": ["transport_ghg"],
    "building_water_ghg": ["building_water_ghg"],
    "total_ghg": ["total_ghg"],
    "physical_activity": ["physical_activity"],
    "health_impacts": ["health_impacts"],
    "stormwater_runoff": ["stormwater_runoff"],
    "food_access": ["food_access"],
    "acs_equity": [],
    "housing_cost_burden": ["housing_cost_burden"],
    "sprawl_index": ["sprawl_index"],
    "tree_canopy": ["tree_canopy"],
    "vmt_fee": ["vmt_fee"],
    "displacement_risk_dynamic": ["displacement_risk_dynamic"],
    "scenario_summary": ["scenario_summary"],
    "sprawl_cost": ["sprawl_cost"],
}


# Module → human-readable label
MODULE_LABELS: dict[str, str] = {
    "env_constraint": "Environmental Constraint",
    "core": "Core Scenario Builder",
    "water_demand": "Water Demand",
    "energy_demand": "Energy Demand",
    "displacement_risk": "Displacement Risk",
    "land_consumption": "Land Consumption",
    "fiscal": "Fiscal Impact",
    "agriculture": "Agriculture",
    "trip_generation": "Trip Generation",
    "trip_distribution": "Trip Distribution",
    "mode_choice": "Mode Choice",
    "vmt": "VMT",
    "internal_capture": "Internal Capture",
    "transport_ghg": "Transportation GHG",
    "building_water_ghg": "Buildings & Water GHG",
    "total_ghg": "Total GHG Emissions",
    "physical_activity": "Physical Activity",
    "health_impacts": "Health Impacts",
    "stormwater_runoff": "Stormwater Runoff",
    "food_access": "Food Access (mRFEI)",
    "acs_equity": "ACS Equity Data Wrapper",
    "housing_cost_burden": "Housing Cost Burden",
    "sprawl_index": "Sprawl Index",
    "tree_canopy": "Tree Canopy / Urban Heat Island",
    "vmt_fee": "VMT Mitigation Fee",
    "displacement_risk_dynamic": "Dynamic Displacement Risk",
    "scenario_summary": "Per-Scenario Summary",
    "sprawl_cost": "Cost of Sprawl per Household",
}


def resolve_module_order(module_names: list[str]) -> list[str]:
    """Resolve requested modules into execution order respecting dependencies.

    If module A depends on module B, B must run first. Missing dependencies
    are automatically prepended, including transitive dependencies.

    Args:
        module_names: List of requested module names.

    Returns:
        Ordered list of modules in execution sequence (topologically sorted).

    Raises:
        ValueError: If an unknown module name is provided.
    """
    unknown = set(module_names) - set(MODULE_DEPENDENCIES)
    if unknown:
        msg = f"Unknown modules: {', '.join(sorted(unknown))}"
        raise ValueError(msg)

    ordered: list[str] = []
    seen: set[str] = set()
    in_progress: set[str] = set()

    def _add_with_deps(module: str) -> None:
        """Post-order traversal: add deps first, then the module."""
        if module in seen:
            return
        if module in in_progress:
            msg = f"Circular dependency detected involving module '{module}'"
            raise ValueError(msg)
        in_progress.add(module)
        for dep in MODULE_DEPENDENCIES.get(module, []):
            _add_with_deps(dep)
        in_progress.discard(module)
        if module not in seen:
            ordered.append(module)
            seen.add(module)

    for module in module_names:
        _add_with_deps(module)

    return ordered


def get_result_table_names(module: str, scenario_id: str) -> list[str]:
    """Return the fully-qualified table names for a module's output."""
    templates = MODULE_RESULT_TABLES.get(module, [])
    return [t.format(scenario_id=scenario_id) for t in templates]


def get_module_label(module: str) -> str:
    """Return the human-readable label for a module."""
    return MODULE_LABELS.get(module, module.replace("_", " ").title())


CANONICAL_COLUMN_NAMES: list[str] = [
    "pop",
    "hh",
    "du",
    "emp",
    "county",
    "geometry",
    "median_income",
    "rent_burden_pct",
    "pct_minority",
    "pct_college_educated",
    "intersection_density",
    "land_development_category",
    "built_form_key",
]


def get_column_mapping_vars(
    column_mapping: dict[str, str],
) -> dict[str, str]:
    """Convert user column mapping into canonical_{name} dbt vars.

    Args:
        column_mapping: User-specified mapping like {'pop': 'population',
            'hh': 'households'}.

    Returns:
        Dict of canonical_{name}: user_column_name for each known name
        found in the mapping. Unknown names are ignored with a warning.
    """
    valid = set(CANONICAL_COLUMN_NAMES)
    vars_: dict[str, str] = {}
    for canonical_name, user_column in column_mapping.items():
        canonical_name = canonical_name.strip().lower()
        if canonical_name in valid:
            vars_[f"canonical_{canonical_name}"] = user_column
        else:
            warnings.warn(
                f"Unknown canonical column name '{canonical_name}' in "
                f"column_mapping. Valid names: {CANONICAL_COLUMN_NAMES}"
            )
    return vars_


def get_vars_for_module(module: str, base_vars: dict[str, Any]) -> dict[str, Any]:
    """Prepare the vars dict for a specific module, inheriting global vars.

    For modules that depend on env_constraint, inject the constraint output
    table name so the core module can reference it.
    """
    vars_ = dict(base_vars)

    if module == "core":
        scenario_id = base_vars.get("scenario_id", "default")
        if "env_constraint" in base_vars.get("completed_modules", []):
            target_schema = base_vars.get("target_schema", "public")
            vars_["constraints_output"] = (
                f"{target_schema}.env_constraint_{scenario_id}"
            )

    return vars_

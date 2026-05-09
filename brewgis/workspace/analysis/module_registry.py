"""Shared module registry — single source of truth for analysis module metadata.

Used by both ``pipeline.py`` (orchestration) and ``tasks.py`` (Celery dispatch)
to avoid duplicated MODULE_DEPENDENCIES, MODULE_RESULT_TABLES, and related mappings.
"""

from __future__ import annotations

from typing import Any

# Module dependency graph: later modules depend on earlier ones
MODULE_DEPENDENCIES: dict[str, list[str]] = {
    "env_constraint": [],
    "core": ["env_constraint"],
    "water_demand": ["core"],
    "energy_demand": ["core"],
    "land_consumption": ["core"],
    "fiscal": ["core"],
    "agriculture": ["core"],
    "trip_generation": ["core"],
    "trip_distribution": ["trip_generation"],
    "mode_choice": ["trip_distribution"],
    "vmt": ["mode_choice"],
}

# Module → result table name templates (formatted with scenario_id)
MODULE_RESULT_TABLES: dict[str, list[str]] = {
    "env_constraint": ["env_constraint_{scenario_id}"],
    "core": ["end_state_{scenario_id}", "increment_{scenario_id}"],
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
}

# Module → dbt select pattern (list of model names to run)
MODULE_DBT_SELECT: dict[str, list[str]] = {
    "env_constraint": ["env_constraint"],
    "core": ["core_end_state", "core_increment"],
    "water_demand": ["water_demand"],
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
}

# Module → human-readable label
MODULE_LABELS: dict[str, str] = {
    "env_constraint": "Environmental Constraint",
    "core": "Core Scenario Builder",
    "water_demand": "Water Demand",
    "energy_demand": "Energy Demand",
    "land_consumption": "Land Consumption",
    "fiscal": "Fiscal Impact",
    "agriculture": "Agriculture",
    "trip_generation": "Trip Generation",
    "trip_distribution": "Trip Distribution",
    "mode_choice": "Mode Choice",
    "vmt": "VMT",
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

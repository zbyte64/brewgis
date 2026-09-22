"""Shared module registry — single source of truth for analysis module metadata.

Used by both ``pipeline.py`` (orchestration) and ``tasks.py`` (Celery dispatch)
to avoid duplicated MODULE_DEPENDENCIES, MODULE_RESULT_TABLES, and related mappings.
"""

from __future__ import annotations

import warnings
from typing import Any

# ``model_fqn`` is re-exported: this registry is where "an analysis module and
# the models implementing it" is defined.
from brewgis.sqlmesh.model_names import model_fqn  # noqa: F401
from brewgis.sqlmesh.model_names import result_schema_name

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
    "vmt": ["trip_generation"],
    "transport_ghg": ["vmt"],
    "building_water_ghg": ["energy_demand", "water_demand"],
    "total_ghg": ["transport_ghg", "building_water_ghg"],
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


# Module → the bare SQLMesh model names whose result views the module produces.
#
# Each analysis model publishes its result view in the scenario's result schema
# (see ``get_result_table_names``); the names here are the model names, which is
# what the views are named after.
MODULE_RESULT_TABLES: dict[str, list[str]] = {
    "env_constraint": ["env_constraint"],
    "core": ["core_end_state", "core_increment"],
    "displacement_risk": ["displacement_risk"],
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
    "vmt": ["vmt"],
    "transport_ghg": ["transport_ghg"],
    "building_water_ghg": ["building_water_ghg"],
    "total_ghg": ["total_ghg"],
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


# Module → the SQLMesh models that implement it, by bare model name. These are
# the models a module's run selects (see ``model_fqn``). Unlike
# ``MODULE_RESULT_TABLES`` this holds only names that really are models —
# ``env_constraint`` and ``acs_equity`` are Django-side/preprocessor steps with
# no SQL model, so they are absent here and contribute nothing to a plan.
MODULE_SQLMESH_SELECTORS: dict[str, list[str]] = {
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
    "vmt": ["vmt"],
    "transport_ghg": ["transport_ghg"],
    "building_water_ghg": ["building_water_ghg"],
    "total_ghg": ["total_ghg"],
    "health_impacts": ["health_impacts"],
    "stormwater_runoff": ["stormwater_runoff"],
    "food_access": ["food_access"],
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
    "vmt": "VMT",
    "transport_ghg": "Transportation GHG",
    "building_water_ghg": "Buildings & Water GHG",
    "total_ghg": "Total GHG Emissions",
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


# Module → one-line description of what the analysis computes, shown on its
# card in the map view's Analysis panel.
MODULE_DESCRIPTIONS: dict[str, str] = {
    "env_constraint": (
        "Applies constraint layers (floodplains, wetlands, steep slopes) to "
        "discount developable land before scenario allocation."
    ),
    "core": (
        "Computes each parcel's end-state population, households, dwelling "
        "units, employment, and building area from its built form assignment."
    ),
    "water_demand": (
        "Estimates residential and non-residential indoor/outdoor water "
        "demand per parcel."
    ),
    "energy_demand": (
        "Estimates residential and non-residential electricity and natural "
        "gas consumption per parcel."
    ),
    "displacement_risk": (
        "Scores displacement vulnerability per parcel from income, rent "
        "burden, and demographic equity indicators."
    ),
    "land_consumption": "Computes developed and impervious land area per parcel.",
    "fiscal": (
        "Computes property tax, sales tax, and service cost impacts per "
        "parcel, and nets them into a fiscal impact per parcel."
    ),
    "agriculture": (
        "Estimates agricultural land use and net return for undeveloped or "
        "rural parcels."
    ),
    "trip_generation": (
        "Computes daily trip generation per parcel from ITE trip rates by land use."
    ),
    "vmt": (
        "Computes vehicle miles traveled per parcel from trip generation, "
        "auto mode share, and average trip length."
    ),
    "transport_ghg": (
        "Computes transportation greenhouse gas emissions (CO2e) from "
        "vehicle miles traveled."
    ),
    "building_water_ghg": (
        "Computes greenhouse gas emissions from building energy use and "
        "water/wastewater treatment."
    ),
    "total_ghg": (
        "Sums transportation and building/water emissions into a total "
        "per-parcel GHG summary."
    ),
    "health_impacts": (
        "Estimates health outcomes (DALYs) from physical activity and "
        "transportation-related air quality changes."
    ),
    "stormwater_runoff": (
        "Estimates stormwater runoff volume from impervious surface area per parcel."
    ),
    "food_access": (
        "Scores food access (mRFEI) from proximity to healthy vs. unhealthy "
        "food retailers."
    ),
    "acs_equity": (
        "Loads ACS demographic and equity indicators (income, rent burden, "
        "demographics) used by other modules."
    ),
    "housing_cost_burden": (
        "Estimates the share of households that are cost-burdened or "
        "severely cost-burdened by housing costs."
    ),
    "sprawl_index": (
        "Scores development pattern compactness from population density, "
        "intersection density, and land use mix."
    ),
    "tree_canopy": "Estimates tree canopy cover and urban heat island exposure per parcel.",
    "vmt_fee": (
        "Calculates VMT mitigation fee revenue and exemptions using a "
        "configurable $/VMT rate (e.g. SB 743 programs)."
    ),
    "displacement_risk_dynamic": (
        "Augments displacement risk with scenario-responsive indicators "
        "showing how infill vs. sprawl patterns affect nearby vulnerability."
    ),
    "scenario_summary": (
        "Aggregates key metrics from every analysis module into one "
        "per-scenario summary."
    ),
    "sprawl_cost": (
        "Divides scenario infrastructure and service costs by household "
        "count to compute cost of sprawl per household."
    ),
}


# Result table (bare SQLMesh model name) → primary output column.
#
# Used to pick a meaningful default symbology attribute for a result layer
# instead of falling back to "first numeric column that isn't parcel_id",
# which tends to land on an incidental pass-through column (e.g.
# area_gross_acres) rather than the analysis's actual headline metric.
TABLE_PRIMARY_COLUMN: dict[str, str] = {
    "core_end_state": "pop",
    "core_increment": "pop",
    "water_demand": "water_demand_total",
    "energy_demand": "energy_total",
    "building_water_ghg": "co2e_total_kg",
    "total_ghg": "co2e_total",
    "transport_ghg": "co2e_total_kg",
    "agriculture": "net_return",
    "sprawl_cost": "infrastructure_cost_per_hh_annual",
    "displacement_risk": "vulnerability_score",
    "displacement_risk_dynamic": "vulnerability_score",
    "food_access": "mrfei",
    "health_impacts": "net_dalys",
    "housing_cost_burden": "cost_burden_pct",
    "land_consumption": "impervious_pct",
    "sprawl_index": "sprawl_index",
    "stormwater_runoff": "runoff_volume_acre_ft",
    "tree_canopy": "canopy_pct",
    "vmt_fee": "fee_revenue_total",
    "vmt": "vmt_total",
    "trip_generation": "trips_total",
    "fiscal_net_impact": "net_fiscal_impact",
    "fiscal_property_tax": "property_tax_revenue",
    "fiscal_sales_tax": "sales_tax_revenue",
    "fiscal_service_costs": "service_cost_total",
}


def get_primary_column(table: str) -> str | None:
    """Return the known headline output column for a result table, if any.

    ``table`` is the bare SQLMesh model name (e.g. ``"water_demand"``), the
    same value passed as ``table=`` to ``register_result_layer``.
    """
    return TABLE_PRIMARY_COLUMN.get(table)


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
    """Return the fully-qualified names of a module's result views."""
    names = MODULE_RESULT_TABLES.get(module, [])
    schema = result_schema_name(scenario_id)
    return [f"{schema}.{name}" for name in names]


def get_module_label(module: str) -> str:
    """Return the human-readable label for a module."""
    return MODULE_LABELS.get(module, module.replace("_", " ").title())


def get_available_analyses() -> list[dict[str, Any]]:
    """Return one entry per user-launchable analysis, for the Analysis panel.

    Excludes modules with no result table of their own (currently just
    ``acs_equity``, a pure upstream data wrapper with nothing to show or
    re-run standalone) — those still run automatically as a dependency of
    whichever card actually needs them.
    """
    analyses = []
    for key, label in MODULE_LABELS.items():
        if not MODULE_RESULT_TABLES.get(key):
            continue
        deps = resolve_module_order([key])
        analyses.append(
            {
                "key": key,
                "label": label,
                "description": MODULE_DESCRIPTIONS.get(key, ""),
                "needs_constraints": "env_constraint" in deps,
                "needs_column_mapping": "core" in deps,
            }
        )
    return analyses


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
    """Convert user column mapping into canonical_{name} pipeline vars.

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

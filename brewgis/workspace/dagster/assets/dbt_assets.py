"""dbt model assets for the analysis pipeline.

Wraps dbt model execution within Dagster's asset graph using the
:class:`~brewgis.workspace.dagster.resources.dbt_resource.DbtCliResource`.
All 40 existing dbt models (SQL + 2 Python) are available for
Dagster-managed materialization.
"""


from typing import Any

from dagster import AssetExecutionContext
from dagster import MaterializeResult
from dagster import asset

from brewgis.workspace.dagster.resources.dbt_resource import DbtCliResource
from brewgis.workspace.dagster.resources.postgres_resource import PostgresResource
from brewgis.workspace.analysis.module_registry import MODULE_DBT_SELECT
from brewgis.workspace.analysis.module_registry import MODULE_DEPENDENCIES


@asset(
    group_name="dbt_staging",
    compute_kind="dbt",
)
def dbt_staging_models(context: AssetExecutionContext, dbt_cli: DbtCliResource) -> MaterializeResult:
    """Materialize all dbt staging models (``staging.*``).

    These wrap imported tables (parcels, base canvas, census, LEHD, POI)
    with clean column names and types.
    """
    result = dbt_cli.run(select=["staging"])
    if not result.success:
        raise RuntimeError(f"dbt staging run failed: {result.error}")
    return MaterializeResult(metadata={"success": True})


# ---------------------------------------------------------------------------
# Per-module dbt analysis assets — one @asset per analysis module
# ---------------------------------------------------------------------------

# Module specifications: (module_name, [dependency_module_names]).
# Dependencies mirror MODULE_DEPENDENCIES; "acs_equity" is resolved to
# the acs_equity_preprocessor asset since there is no dbt model for it.
_MODULE_SPECS: list[tuple[str, list[str]]] = [
    ("env_constraint", []),
    ("core", ["env_constraint"]),
    ("water_demand", ["core"]),
    ("energy_demand", ["core"]),
    ("land_consumption", ["core"]),
    ("fiscal", ["core"]),
    ("agriculture", ["core"]),
    ("trip_generation", ["core"]),
    ("trip_distribution", ["trip_generation"]),
    ("mode_choice", ["trip_distribution"]),
    ("vmt", ["mode_choice"]),
    ("internal_capture", ["trip_distribution"]),
    ("transport_ghg", ["vmt"]),
    ("building_water_ghg", ["energy_demand", "water_demand"]),
    ("total_ghg", ["transport_ghg", "building_water_ghg"]),
    ("physical_activity", ["mode_choice", "trip_distribution"]),
    ("health_impacts", ["physical_activity", "transport_ghg"]),
    ("stormwater_runoff", ["land_consumption"]),
    ("food_access", ["core"]),
    ("displacement_risk", ["core", "acs_equity"]),
    ("housing_cost_burden", ["core", "acs_equity"]),
    ("sprawl_index", ["core"]),
    ("tree_canopy", ["core"]),
    ("vmt_fee", ["vmt"]),
    ("displacement_risk_dynamic", ["displacement_risk", "acs_equity"]),
    ("scenario_summary", [
        "core", "vmt", "transport_ghg", "total_ghg", "health_impacts",
        "housing_cost_burden", "sprawl_index", "water_demand",
        "energy_demand", "land_consumption",
    ]),
    ("sprawl_cost", ["core", "fiscal"]),
]


def _make_module_asset(module: str, deps_modules: list[str]):
    """Create a per-module dbt analysis asset for *module*.

    Translates dependency module names into Dagster asset keys,
    handling the acs_equity → acs_equity_preprocessor mapping.
    """
    dep_asset_keys: list[str] = []
    for dep in deps_modules:
        if dep == "acs_equity":
            dep_asset_keys.append("acs_equity_preprocessor")
        else:
            dep_asset_keys.append(f"{dep}_analysis")

    select = MODULE_DBT_SELECT[module]
    fn_name = f"{module}_analysis"

    @asset(
        deps=dep_asset_keys,
        group_name="analysis",
        compute_kind="dbt",
        name=fn_name,
    )
    def _asset(context: AssetExecutionContext, dbt_cli: DbtCliResource) -> MaterializeResult:
        result = dbt_cli.run(select=select)
        if not result.success:
            raise RuntimeError(f"{module} failed: {result.error}")
        return MaterializeResult(metadata={"success": True})

    _asset.__name__ = fn_name
    _asset.__qualname__ = fn_name
    return _asset


ANALYSIS_ASSETS = [
    _make_module_asset(m, d)
    for m, d in _MODULE_SPECS
    if MODULE_DBT_SELECT.get(m, [])
]
@asset(group_name="preprocessing", compute_kind="python")
def building_types_export(
    context: AssetExecutionContext,
    postgres: PostgresResource,
) -> MaterializeResult:
    """Export BuildingType Django records to a flat PostGIS table for dbt."""
    from brewgis.workspace.analysis.data_export import export_building_types
    count = export_building_types(schema="public", table="built_forms")
    return MaterializeResult(metadata={"rows": count})


@asset(
    group_name="preprocessing",
    compute_kind="python",
    deps=["trip_distribution_analysis"],
)
def internal_capture_preprocessor(
    context: AssetExecutionContext,
    postgres: PostgresResource,
) -> MaterializeResult:
    """Preprocess transport data: compute OD network distance matrix.

    Creates ``trip_distribution_inputs`` table consumed by downstream
    transport dbt models (mode choice, assignment).
    """
    from brewgis.workspace.analysis.transport.preprocessors import (  # noqa: PLC0415
        DistanceMatrixPreprocessor,
    )
    preprocessor = DistanceMatrixPreprocessor()
    result = preprocessor.compute_distance_matrix(
        schema="public",
        end_state_table="end_state_default",
        scenario_id="default",
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error", "Distance matrix computation failed"))
    pair_count = result.get("pair_count", 0)
    return MaterializeResult(metadata={"pair_count": pair_count})


@asset(
    group_name="preprocessing",
    compute_kind="python",
    deps=["core_analysis"],
)
def food_access_preprocessor(
    context: AssetExecutionContext,
    postgres: PostgresResource,
) -> MaterializeResult:
    """Preprocess food access data: compute mRFEI from OSM POIs.

    Creates ``food_access_inputs`` table consumed by the food_access
    dbt module.
    """
    from brewgis.workspace.analysis.food_access.preprocessor import (  # noqa: PLC0415
        FoodAccessPreprocessor,
    )
    preprocessor = FoodAccessPreprocessor()
    result = preprocessor.compute_mrfei(
        schema="public",
        end_state_table="end_state_default",
        scenario_id="default",
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error", "mRFEI computation failed"))
    return MaterializeResult(metadata={"method": result.get("method", "unknown")})


@asset(
    group_name="preprocessing",
    compute_kind="python",
    deps=["core_analysis"],
)
def acs_equity_preprocessor(
    context: AssetExecutionContext,
    postgres: PostgresResource,
) -> MaterializeResult:
    """Preprocess ACS equity data: join ACS variables to parcels.

    Updates the ``base_canvas`` table with median income, rent burden,
    minority percentage, and education level from ACS block-group data.
    Falls back to uniform national defaults when ACS data is unavailable.
    """
    from brewgis.workspace.analysis.equity.preprocessor import (  # noqa: PLC0415
        run_acs_equity_preprocessor,
    )
    result = run_acs_equity_preprocessor({
        "target_schema": "public",
        "base_canvas_table": "base_canvas",
    })
    if not result.get("success"):
        raise RuntimeError(result.get("error", "ACS equity preprocessing failed"))
    return MaterializeResult(metadata={"method": result.get("method", "unknown")})

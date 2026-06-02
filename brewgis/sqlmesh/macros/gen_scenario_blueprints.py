from __future__ import annotations

from sqlmesh import macro


@macro()
def gen_scenario_blueprints(
    evaluator, built_form_table: str = "public.built_forms"
) -> str:
    """Generate blueprint parameter rows from the built forms table.

    Reads the built forms export table (populated from Django BuildingType
    records) and produces blueprint parameter rows keyed by built_form_key.
    These rows define the physical, demographic, and resource parameters
    used by allocation models.

    The built_forms table is created by the ``export_building_types()``
    management command (see ``brewgis.workspace.analysis.data_export``).

    Returns SQL for a subquery suitable for use in CTEs or joins.
    Each row maps a built_form_key to its full set of allocation parameters::

        SELECT * FROM (@gen_scenario_blueprints('public.built_forms')) bp
        JOIN parcels p ON p.built_form_key = bp.built_form_key

    Args:
        built_form_table: Qualified built forms table (default: public.built_forms).

    Returns:
        SQL subquery producing blueprint parameter rows.
    """
    return f"""SELECT
    key AS built_form_key,
    COALESCE(du_per_acre, 0.0) AS du_per_acre,
    COALESCE(emp_per_acre, 0.0) AS emp_per_acre,
    COALESCE(far, 0.0) AS far,
    COALESCE(household_size, 2.5) AS household_size,
    COALESCE(vacancy_rate, 5.0) AS vacancy_rate,
    COALESCE(building_coverage, 0.0) AS building_coverage,
    COALESCE(indoor_water_rate, 0.0) AS indoor_water_rate,
    COALESCE(outdoor_water_rate, 0.0) AS outdoor_water_rate,
    COALESCE(irrigable_area_fraction, 0.0) AS irrigable_area_fraction,
    COALESCE(electricity_eui, 0.0) AS electricity_eui,
    COALESCE(gas_eui, 0.0) AS gas_eui,
    COALESCE(jobs_by_sector, '{{}}'::jsonb) AS jobs_by_sector,
    vintage,
    COALESCE(trip_rate_override, 0.0) AS trip_rate_override,
    ite_land_use_code,
    COALESCE(pass_by_trip_pct, 0.0) AS pass_by_trip_pct
FROM {built_form_table}"""

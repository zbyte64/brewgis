{#
    Per-Scenario Summary View (ROADMAP_2 Phase 2d)

    Aggregates key metrics from all module outputs into a single summary
    per scenario. Used by the Multi-Scenario Comparator (Phase 3a),
    Data Journalism Export (Phase 3b), and Scenario Brief (Phase 3c).

    Config vars:
        scenario_id: Unique scenario identifier.

    Source tables:
        {{ ref('core_end_state') }}
        {{ ref('vmt') }}
        {{ ref('transport_ghg') }}
        {{ ref('total_ghg') }}
        {{ ref('health_impacts') }}
        {{ ref('housing_cost_burden') }}
        {{ ref('sprawl_index') }}
        {{ ref('water_demand') }}
        {{ ref('energy_demand') }}
        {{ ref('land_consumption') }}

    Output columns:
        scenario_id, scenario_name,
        population, households, dwelling_units_total, employment_total,
        vmt_total, vmt_per_capita,
        co2e_total, co2e_per_capita,
        cost_burdened_hh_pct, displacement_risk_pct,
        avg_sprawl_index,
        water_demand_total_af, energy_demand_total_mwh,
        land_consumed_acres, land_consumed_pct,
        net_dalys, geom

    Materialized as: {{ var('target_schema') }}.scenario_summary_{{ var('scenario_id') }}
#}
{{ set_vars({'scenario_id': 'demo'}) }}
{{ config(alias='scenario_summary_' ~ var('scenario_id')) }}

{% set metrics = [
    ('core_end_state', 'population'),
    ('core_end_state', 'households'),
    ('core_end_state', 'dwelling_units_total'),
    ('core_end_state', 'employment_total'),
    ('vmt', 'vmt_total'),
    ('total_ghg', 'co2e_total'),
    ('water_demand', 'water_demand_af'),
    ('land_consumption', 'acres_consumed'),
    ('health_impacts', 'net_dalys'),
] %}

WITH metrics AS (
    SELECT
        {% for table, col in metrics %}
        {{ summarize_metric(table, col) }}{% if not loop.last %},{% endif %}
        {% endfor %},
        (SELECT COALESCE(SUM(population), 0) FROM {{ ref('core_end_state') }}
            WHERE geom IS NOT NULL
        ) AS total_pop_for_co2e_per_capita,
        (SELECT COALESCE(SUM(electricity_mwh + gas_mwh), 0) FROM {{ ref('energy_demand') }}) AS total_energy_demand,
        (SELECT COALESCE(AVG(vmt_per_capita), 0) FROM {{ ref('vmt') }} WHERE population > 0) AS avg_vmt_per_capita,
        (SELECT COALESCE(AVG(cost_burden_pct), 0) FROM {{ ref('housing_cost_burden') }}) AS avg_cost_burden_pct,
        (SELECT COALESCE(AVG(sprawl_index), 0) FROM {{ ref('sprawl_index') }}) AS avg_sprawl_index,
        (SELECT COALESCE(AVG(impervious_pct), 0) FROM {{ ref('land_consumption') }} WHERE gross_acres > 0) AS avg_impervious_pct,
        (SELECT COALESCE(AVG(displacement_risk_category), 0)
            FROM {{ ref('displacement_risk') }}
            WHERE displacement_risk_category IN ('at_risk', 'displacement_pressure')
        ) AS displacement_risk_parcels
)
SELECT
    '{{ var('scenario_id') }}'::text AS scenario_id,
    total_population,
    total_households,
    total_dwelling_units_total AS dwelling_units_total,
    total_employment,
    total_vmt AS vmt_total,
    ROUND((total_vmt / NULLIF(total_population, 0))::numeric, 2) AS vmt_per_capita,
    total_co2e AS co2e_total_kg,
    ROUND((total_co2e / NULLIF(total_pop_for_co2e_per_capita, 0))::numeric, 2) AS co2e_per_capita_kg,
    ROUND(avg_cost_burden_pct::numeric, 1) AS cost_burdened_hh_pct,
    avg_sprawl_index,
    total_water_demand AS water_demand_total_af,
    total_energy_demand AS energy_demand_total_mwh,
    total_land_consumed AS land_consumed_acres,
    ROUND(avg_impervious_pct::numeric, 1) AS land_consumed_pct,
    total_net_dalys AS net_dalys
FROM metrics

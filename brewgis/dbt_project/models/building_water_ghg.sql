{#
    G2 — Buildings & Water GHG

    Computes greenhouse gas emissions (CO₂e) from building energy consumption
    and water/wastewater treatment. Uses eGRID emission factors for electricity
    and standard factors for natural gas.

    Inputs (via dbt vars):
        target_schema: Schema for output.
        scenario_id: Unique scenario identifier.
        ghg_egrid_co2_per_kwh: CO₂e per kWh for electricity (default: 0.417 kg — US average).
        ghg_gas_co2_per_kwh: CO₂e per kWh for natural gas (default: 0.181 kg).
        ghg_water_supply_kwh_per_mg: kWh per million gallons for water supply (default: 1427).
        ghg_wastewater_kwh_per_mg: kWh per million gallons for wastewater (default: 1911).

    Source tables:
        {{ var('target_schema') }}.energy_demand_{{ var('scenario_id') }}
        {{ var('target_schema') }}.water_demand_{{ var('scenario_id') }}

    Output columns:
        parcel_id, co2e_energy_total_kg, co2e_water_total_kg,
        co2e_total_kg, co2e_per_capita_kg, geom

    Materialized as: {{ var('target_schema') }}.building_water_ghg_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='building_water_ghg_' ~ scenario_id) }}

{%- set egrid_co2_per_kwh = var('ghg_egrid_co2_per_kwh', 0.417) -%}
{%- set gas_co2_per_kwh = var('ghg_gas_co2_per_kwh', 0.181) -%}
{%- set water_supply_kwh_per_mg = var('ghg_water_supply_kwh_per_mg', 1427) -%}
{%- set wastewater_kwh_per_mg = var('ghg_wastewater_kwh_per_mg', 1911) -%}

WITH energy_data AS (
    SELECT
        ed.parcel_id,
        ed.energy_electricity_res,
        ed.energy_gas_res,
        ed.energy_electricity_nonres,
        ed.energy_gas_nonres,
        wd.water_demand_total,
        es.population,
        es.geom
    FROM {{ ref('energy_demand') }} AS ed
    LEFT JOIN {{ ref('water_demand') }} AS wd
        ON ed.parcel_id = wd.parcel_id
    LEFT JOIN {{ ref('core_end_state') }} AS es
        ON ed.parcel_id = es.parcel_id
)

SELECT
    parcel_id,

    -- Building energy CO₂e (kg): electric kWh × eGRID factor + gas kWh × gas factor
    COALESCE(
        (energy_electricity_res + energy_electricity_nonres) * {{ egrid_co2_per_kwh }}
        + (energy_gas_res + energy_gas_nonres) * {{ gas_co2_per_kwh }},
        0.0
    ) AS co2e_energy_total_kg,

    -- Water/wastewater CO₂e (kg):
    -- Water demand (L) → MG × (supply + wastewater kWh/MG) × eGRID factor
    -- 1 MG = 3,785,411.8 L
    CASE
        WHEN COALESCE(water_demand_total, 0.0) > 0
            THEN
                water_demand_total / 3785411.8
                * ({{ water_supply_kwh_per_mg }} + {{ wastewater_kwh_per_mg }})
                * {{ egrid_co2_per_kwh }}
        ELSE 0.0
    END AS co2e_water_total_kg,

    -- Total CO₂e
    COALESCE(
        (energy_electricity_res + energy_electricity_nonres) * {{ egrid_co2_per_kwh }}
        + (energy_gas_res + energy_gas_nonres) * {{ gas_co2_per_kwh }},
        0.0
    )
    + CASE
        WHEN COALESCE(water_demand_total, 0.0) > 0
            THEN
                water_demand_total / 3785411.8
                * ({{ water_supply_kwh_per_mg }} + {{ wastewater_kwh_per_mg }})
                * {{ egrid_co2_per_kwh }}
        ELSE 0.0
    END AS co2e_total_kg,

    -- Per-capita CO₂e
    CASE
        WHEN population > 0
            THEN (
                COALESCE(
                    (energy_electricity_res + energy_electricity_nonres) * {{ egrid_co2_per_kwh }}
                    + (energy_gas_res + energy_gas_nonres) * {{ gas_co2_per_kwh }},
                    0.0
                )
                + CASE
                    WHEN COALESCE(water_demand_total, 0.0) > 0
                        THEN
                            water_demand_total / 3785411.8
                            * ({{ water_supply_kwh_per_mg }} + {{ wastewater_kwh_per_mg }})
                            * {{ egrid_co2_per_kwh }}
                    ELSE 0.0
                END
            ) / population
        ELSE 0.0
    END AS co2e_per_capita_kg,

    geom
FROM energy_data

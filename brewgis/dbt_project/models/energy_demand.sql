{#
    Energy Demand Model — Scenario Builder

    Computes residential and non-residential energy demand (kWh/year)
    for each parcel, using end-state allocation and BuildingType coefficients.

    Residential energy uses EUI (kWh/m2/yr) applied to estimated dwelling
    unit floor area (derived from FAR and parcel acreage).

    Inputs (via dbt vars):
        target_schema: Schema for output.
        scenario_id: Unique scenario identifier.
        res_far_default: Default residential FAR for unit area estimation (default: 0.5).

    Source table: {{ var('target_schema') }}.end_state_{{ var('scenario_id') }}

    Output columns:
        parcel_id, gross_acres, acres_developed,
        energy_electricity_res, energy_gas_res,
        energy_electricity_nonres, energy_gas_nonres,
        energy_total, energy_intensity_kwh_per_sqft,
        dwelling_units_total, building_sqft_total,
        population, employment_total,
        geom

    Materialized as: {{ var('target_schema') }}.energy_demand_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='energy_demand_' ~ scenario_id) }}

{%- set res_far = var('res_far_default', 0.5) -%}
{%- set res_electric = "dwelling_units_total * electricity_eui * 0.092903 * (acres_developed * 43560.0 * " ~ res_far ~ " / NULLIF(dwelling_units_total, 0))" -%}
{%- set res_gas = "dwelling_units_total * gas_eui * 0.092903 * (acres_developed * 43560.0 * " ~ res_far ~ " / NULLIF(dwelling_units_total, 0))" -%}
{%- set nonres_electric = "building_sqft_total * 0.092903 * electricity_eui" -%}
{%- set nonres_gas = "building_sqft_total * 0.092903 * gas_eui" -%}

SELECT
    es.parcel_id,
    es.gross_acres,
    es.acres_developed,

    -- Residential electric (kWh/yr): dwelling units * avg_unit_area_m2 * EUI (kWh/m2/yr)
    -- Avg unit area = acres_developed * 43560 * FAR / dwelling_units
    COALESCE({{ res_electric }}, 0.0) AS energy_electricity_res,

    -- Residential gas (kWh/yr)
    COALESCE({{ res_gas }}, 0.0) AS energy_gas_res,

    -- Non-residential electric (kWh/yr): building_sqft -> m2 * EUI
    COALESCE({{ nonres_electric }}, 0.0) AS energy_electricity_nonres,

    -- Non-residential gas (kWh/yr)
    COALESCE({{ nonres_gas }}, 0.0) AS energy_gas_nonres,

    -- Total energy (kWh/yr)
    COALESCE({{ res_electric }}, 0.0)
    + COALESCE({{ res_gas }}, 0.0)
    + COALESCE({{ nonres_electric }}, 0.0)
    + COALESCE({{ nonres_gas }}, 0.0)
    AS energy_total,

    -- Energy intensity (kWh/sqft)
    CASE WHEN es.building_sqft_total > 0
        THEN (COALESCE({{ res_electric }}, 0.0)
            + COALESCE({{ res_gas }}, 0.0)
            + COALESCE({{ nonres_electric }}, 0.0)
            + COALESCE({{ nonres_gas }}, 0.0))
            / es.building_sqft_total
        ELSE 0.0
    END AS energy_intensity_kwh_per_sqft,

    es.dwelling_units_total,
    es.building_sqft_total,
    es.population,
    es.employment_total,
    es.geom

FROM {{ ref('core_end_state') }} AS es

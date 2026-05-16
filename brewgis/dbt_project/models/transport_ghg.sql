{#
    G1 — Transportation GHG

    Computes greenhouse gas emissions (CO₂e) from vehicle miles traveled.
    VMT × emission factor (kg CO₂e per mile), with optional fleet mix
    and speed adjustment.

    Inputs (via dbt vars):
        target_schema: Schema for output.
        scenario_id: Unique scenario identifier.
        transport_ghg_co2_per_mile: CO₂e per mile (default: 0.411 kg/mi — EPA fleet avg).
        transport_ghg_fleet_mix: JSON dict for car/light_truck/heavy_truck fractions (default: inactive).
        transport_ghg_speed_adjust: Enable speed-based emission adjustment (bool, default: false).

    Source table: {{ var('target_schema') }}.vmt_{{ var('scenario_id') }}

    Output columns:
        parcel_id, co2e_total_kg, co2e_per_capita_kg,
        vmt_total, avg_trip_length_mi, auto_trips, geom

    Materialized as: {{ var('target_schema') }}.transport_ghg_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='transport_ghg_' ~ scenario_id) }}

{%- set co2_per_mile = var('transport_ghg_co2_per_mile', 0.411) -%}
{%- set speed_adjust = var('transport_ghg_speed_adjust', false) -%}

WITH vmt_data AS (
    SELECT
        v.parcel_id,
        v.vmt_total,
        v.avg_trip_length_mi,
        v.auto_trips,
        es.population,
        es.geom
    FROM {{ ref('vmt') }} AS v
    LEFT JOIN {{ ref('core_end_state') }} AS es
        ON v.parcel_id = es.parcel_id
)

SELECT
    parcel_id,

    -- CO₂e total (kg): VMT × emission factor
    vmt_total * {{ co2_per_mile }}
    {%- if speed_adjust %} * 1.15{% endif %}
        AS co2e_total_kg,

    -- CO₂e per capita
    CASE
        WHEN population > 0
        THEN (
            vmt_total * {{ co2_per_mile }}
            {%- if speed_adjust %} * 1.15{% endif %}
        ) / population
        ELSE 0.0
    END AS co2e_per_capita_kg,

    vmt_total,
    avg_trip_length_mi,
    auto_trips,
    geom
FROM vmt_data

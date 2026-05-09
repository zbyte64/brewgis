{#
    G3 — Total GHG Summary

    Aggregates transportation (G1) and building/water (G2) emissions into
    a per-parcel summary.

    Dependencies:
        transport_ghg (G1), building_water_ghg (G2)

    Output columns:
        parcel_id, co2e_transport, co2e_buildings, co2e_water, co2e_total

    Materialized as: {{ var('target_schema') }}.total_ghg_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='total_ghg_' ~ scenario_id) }}

SELECT
    COALESCE(t.parcel_id, b.parcel_id) AS parcel_id,
    COALESCE(t.co2e_total_kg, 0.0) AS co2e_transport,
    COALESCE(b.co2e_energy_total_kg, 0.0) AS co2e_buildings,
    COALESCE(b.co2e_water_total_kg, 0.0) AS co2e_water,
    COALESCE(t.co2e_total_kg, 0.0)
    + COALESCE(b.co2e_total_kg, 0.0) AS co2e_total
FROM {{ ref('transport_ghg') }} AS t
FULL OUTER JOIN {{ ref('building_water_ghg') }} AS b
    ON t.parcel_id = b.parcel_id

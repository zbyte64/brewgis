{#
    VMT Model — T4 Module

    Computes vehicle miles traveled (VMT) from mode choice and trip distribution.
    VMT = auto trips * avg trip length (km) * 0.621371 (km→mi) * circuity factor.

    Inputs (via dbt vars):
        target_schema: Schema for output.
        scenario_id: Unique scenario identifier.
        transport_circuity_factor: Road network directness adjustment (default: 1.2).

    Source tables:
        {{ var('target_schema') }}.mode_choice_{{ var('scenario_id') }}
        {{ var('target_schema') }}.trip_distribution_{{ var('scenario_id') }}

    Output columns:
        parcel_id, vmt_total, vmt_per_capita, auto_trips,
        avg_trip_length_mi, geom

    Materialized as: {{ var('target_schema') }}.vmt_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='vmt_' ~ scenario_id) }}

{%- set circuity_factor = var('transport_circuity_factor', 1.2) -%}

WITH mode_trips AS (
    SELECT
        mc.parcel_id,
        mc.trips_auto AS auto_trips,
        td.avg_trip_length_km,
        es.population,
        es.geom
    FROM {{ ref('mode_choice') }} AS mc
    LEFT JOIN {{ ref('trip_distribution') }} AS td
        ON mc.parcel_id = td.parcel_id
    LEFT JOIN {{ ref('core_end_state') }} AS es
        ON mc.parcel_id = es.parcel_id
)

SELECT
    parcel_id,

    -- VMT total: auto_trips * avg_trip_length_km * 0.621371 (km→mi) * circuity_factor
    auto_trips * avg_trip_length_km * 0.621371 * {{ circuity_factor }}
        AS vmt_total,

    -- VMT per capita
    CASE WHEN population > 0
        THEN (auto_trips * avg_trip_length_km * 0.621371 * {{ circuity_factor }})
             / population
        ELSE 0.0
    END AS vmt_per_capita,

    auto_trips,
    avg_trip_length_km * 0.621371 AS avg_trip_length_mi,
    geom
FROM mode_trips

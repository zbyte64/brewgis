{#
    H1 — Physical Activity (MET-hours)

    Computes metabolic equivalent (MET) hours from active transportation
    (walking and cycling) using mode choice trip data and trip distribution
    distances.

    Formula:
        MET-hours = trips × (distance_km / speed_kmh) × MET

    Inputs (via dbt vars):
        target_schema: Schema for output.
        scenario_id: Unique scenario identifier.
        health_walk_met: Walking MET value (default: 3.5 — moderate pace, ~3 mph).
        health_bike_met: Biking MET value (default: 6.0 — moderate pace, ~10 mph).
        health_walk_speed_kmh: Walking speed in km/h (default: 4.8).
        health_bike_speed_kmh: Biking speed in km/h (default: 16.0).

    Source tables:
        {{ var('target_schema') }}.mode_choice_{{ var('scenario_id') }}
        {{ var('target_schema') }}.trip_distribution_{{ var('scenario_id') }}

    Output columns:
        parcel_id, walk_met_hours, bike_met_hours, total_met_hours,
        walk_trips, bike_trips, active_trip_share, geom

    Materialized as: {{ var('target_schema') }}.physical_activity_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='physical_activity_' ~ scenario_id) }}

{%- set walk_met = var('health_walk_met', 3.5) -%}
{%- set bike_met = var('health_bike_met', 6.0) -%}
{%- set walk_speed_kmh = var('health_walk_speed_kmh', 4.8) -%}
{%- set bike_speed_kmh = var('health_bike_speed_kmh', 16.0) -%}

WITH mode_data AS (
    SELECT
        mc.parcel_id,
        mc.trips_walk AS walk_trips,
        mc.trips_bike AS bike_trips,
        mc.trips_auto AS auto_trips,
        mc.trips_transit AS transit_trips,
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

    -- Walking MET-hours: walk_trips × (avg_trip_length_km / walk_speed_kmh) × MET
    COALESCE(walk_trips * (avg_trip_length_km / {{ walk_speed_kmh }}) * {{ walk_met }}, 0.0)
        AS walk_met_hours,

    -- Biking MET-hours: bike_trips × (avg_trip_length_km / bike_speed_kmh) × MET
    COALESCE(bike_trips * (avg_trip_length_km / {{ bike_speed_kmh }}) * {{ bike_met }}, 0.0)
        AS bike_met_hours,

    -- Total MET-hours
    COALESCE(walk_trips * (avg_trip_length_km / {{ walk_speed_kmh }}) * {{ walk_met }}, 0.0)
    + COALESCE(bike_trips * (avg_trip_length_km / {{ bike_speed_kmh }}) * {{ bike_met }}, 0.0)
        AS total_met_hours,

    walk_trips,
    bike_trips,

    -- Active trip share (walk + bike / total trips)
    COALESCE(
        (COALESCE(walk_trips, 0.0) + COALESCE(bike_trips, 0.0))
        / NULLIF(
            COALESCE(walk_trips, 0.0) + COALESCE(bike_trips, 0.0)
            + COALESCE(auto_trips, 0.0) + COALESCE(transit_trips, 0.0),
            0.0
        ),
        0.0
    ) AS active_trip_share,

    geom
FROM mode_data

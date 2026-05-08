{#
    Trip Generation Model — T1 Module

    Computes daily trip generation per parcel from ITE trip generation rates.
    Uses BuildingType trip_rate_override (if set) or ITE default rates,
    applies pass-by reduction for non-residential trips, and splits into
    home-based work (HBW), home-based other (HBO), and non-home-based (NHB).

    Inputs (via dbt vars):
        target_schema: Schema for output.
        scenario_id: Unique scenario identifier.
        source_schema: Schema containing source tables (built_forms).
        built_form_table: Table name for built form definitions (default: built_forms).
        transport_nonres_trip_rate: Trips/1000 sqft/day (default: 42.94).
        transport_pass_by_pct: Pass-by reduction fraction (default: 0.0).
        transport_hbw_pct: Home-based work share (default: 0.18).
        transport_hbo_pct: Home-based other share (default: 0.42).
        transport_nhb_pct: Non-home-based share (default: 0.40).

    Source table: {{ var('target_schema') }}.end_state_{{ var('scenario_id') }}

    Output columns:
        parcel_id, gross_acres, trips_total, trips_res, trips_nonres,
        trips_hbw, trips_hbo, trips_nhb, geom

    Materialized as: {{ var('target_schema') }}.trip_generation_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='trip_generation_' ~ scenario_id) }}

{%- set source_schema = var('source_schema') -%}
{%- set built_form_table = var('built_form_table', 'built_forms') -%}

{%- set nonres_rate = var('transport_nonres_trip_rate', 42.94) -%}
{%- set pass_by_pct = var('transport_pass_by_pct', 0.0) -%}
{%- set hbw_pct = var('transport_hbw_pct', 0.18) -%}
{%- set hbo_pct = var('transport_hbo_pct', 0.42) -%}
{%- set nhb_pct = var('transport_nhb_pct', 0.40) -%}

WITH parcel_base AS (
    SELECT
        es.parcel_id,
        es.gross_acres,
        es.dwelling_units_total,
        es.building_sqft_total,
        es.built_form_id,
        es.land_dev_category,
        es.intersection_density,
        es.population,
        es.employment_total,
        es.geom,
        bf.trip_rate_override,
        bf.pass_by_trip_pct
    FROM {{ var('target_schema') }}.end_state_{{ var('scenario_id') }} AS es
    LEFT JOIN {{ source_schema }}.{{ built_form_table }} AS bf
        ON es.built_form_id = bf.key
),

trip_rates AS (
    SELECT
        parcel_id,
        gross_acres,
        dwelling_units_total,
        building_sqft_total,
        geom,

        -- Residential trips: dwelling_units * trip_rate_override
        -- (trip_rate_override is trips/dwelling_unit for residential)
        COALESCE(dwelling_units_total * trip_rate_override, 0.0)
            AS trips_res,

        -- Non-residential trips: (building_sqft_total / 1000) * nonres_rate
        COALESCE((building_sqft_total / 1000.0) * {{ nonres_rate }}, 0.0)
            AS trips_nonres_raw,

        COALESCE(pass_by_trip_pct, 0.0) AS pass_by_trip_pct
    FROM parcel_base
)

SELECT
    parcel_id,
    gross_acres,

    -- Total primary trips with pass-by reduction
    (trips_res + trips_nonres_raw * (1.0 - pass_by_trip_pct))
        AS trips_total,

    trips_res,

    -- Non-residential trips after pass-by reduction
    trips_nonres_raw * (1.0 - pass_by_trip_pct)
        AS trips_nonres,

    -- Trip purpose split
    (trips_res + trips_nonres_raw * (1.0 - pass_by_trip_pct)) * {{ hbw_pct }}
        AS trips_hbw,

    (trips_res + trips_nonres_raw * (1.0 - pass_by_trip_pct)) * {{ hbo_pct }}
        AS trips_hbo,

    (trips_res + trips_nonres_raw * (1.0 - pass_by_trip_pct)) * {{ nhb_pct }}
        AS trips_nhb,

    geom
FROM trip_rates

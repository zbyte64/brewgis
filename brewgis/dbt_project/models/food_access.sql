{#
    H3 — Food Access (mRFEI)

    Computes the Modified Retail Food Environment Index (mRFEI) per parcel
    using OSM Points of Interest data.

    Formula:
        mRFEI = healthy / (healthy + unhealthy) * 100

    Categories:
        <25:    food_desert (lowest healthy food access)
        25-50:  low_access
        50-75:  moderate_access
        >75:    high_access (highest healthy food access)

    Inputs (via dbt vars):
        target_schema: Schema for output.
        scenario_id: Unique scenario identifier.

    Source tables:
        {{ var('target_schema') }}.food_access_inputs_{{ var('scenario_id') }}

    Output columns:
        parcel_id, gross_acres, population, households, healthy_count,
        unhealthy_count, mrfei, food_desert, food_access_category, geom

    Materialized as: {{ var('target_schema') }}.food_access_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='food_access_' ~ scenario_id) }}

WITH food_data AS (
    SELECT
        es.parcel_id,
        es.gross_acres,
        es.population,
        es.households,
        fi.healthy_count,
        fi.unhealthy_count,
        fi.mrfei,
        es.geom
    FROM {{ ref('core_end_state') }} AS es
    LEFT JOIN {{ var('target_schema') }}.food_access_inputs_{{ scenario_id }} AS fi
        ON es.parcel_id = fi.parcel_id
)

SELECT
    parcel_id,
    gross_acres,
    population,
    households,
    COALESCE(healthy_count, 0) AS healthy_count,
    COALESCE(unhealthy_count, 0) AS unhealthy_count,
    mrfei,
    COALESCE(mrfei < 25, FALSE) AS food_desert,
    CASE
        WHEN mrfei IS NULL THEN NULL
        WHEN mrfei < 25 THEN 'food_desert'
        WHEN mrfei < 50 THEN 'low_access'
        WHEN mrfei < 75 THEN 'moderate_access'
        ELSE 'high_access'
    END AS food_access_category,
    geom
FROM food_data

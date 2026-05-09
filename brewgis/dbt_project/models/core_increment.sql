{#
    Core Increment Model — Scenario Builder Delta

    Computes the delta between the end-state allocation and the existing
    (base canvas) condition for each attribute.  This shows the change
    from baseline for every output metric.

    The increment is computed as:

        increment = COALESCE(end_state.value, 0) - COALESCE(base.value, 0)

    For parcel area columns, the increment preserves the sign convention
    (positive = development adds to this category).

    Output columns:
        Same attribute columns as end_state, but as deltas.
        parcel_id (from end_state)

    Materialized as: {{ var('target_schema') }}.increment_{{ var('scenario_id') }}
#}

{{ config(alias='increment_' ~ var('scenario_id')) }}

{%- set source_schema = var('source_schema') -%}
{%- set base_canvas = var('base_canvas_table', 'base_canvas') -%}

{%- set all_cols = [
    "population", "households", "dwelling_units_total",
    "dwelling_units_sf_ll", "dwelling_units_sf_sl",
    "dwelling_units_attached_sf", "dwelling_units_mf_2_4", "dwelling_units_mf_5p",
    "employment_total",
    "building_sqft_total", "building_sqft_residential", "building_sqft_commercial",
    "building_sqft_office", "building_sqft_industrial", "building_sqft_public",
    "building_sqft_retail", "building_sqft_wholesale", "building_sqft_education",
    "building_sqft_healthcare", "building_sqft_hotel_lodging", "building_sqft_entertainment",
    "building_sqft_other",
    "res_irrigated_sqft", "com_irrigated_sqft",
    "parcel_acres_developed", "parcel_acres_agriculture",
    "parcel_acres_open_space", "parcel_acres_vacant",
    "intersection_density",
] -%}

WITH end_state AS (
    SELECT * FROM {{ ref('core_end_state') }}
),

base AS (
    SELECT * FROM {{ source_schema }}.{{ base_canvas }}
)

SELECT
    -- Parcel ID for joining
    COALESCE(es.parcel_id, b.parcel_id) AS parcel_id,

    -- Base acres (from base canvas, same for all scenarios)
    b.gross_acres,

    es.acres_developable,
    es.acres_developed,
    es.land_dev_category,

    -- All attribute deltas
    {{ delta_columns(all_cols, "es", "b") }},

    -- Geometry (from end state — use base if no end state)
    COALESCE(es.geom, b.geom) AS geom
FROM end_state AS es
FULL OUTER JOIN base AS b ON es.parcel_id = b.parcel_id

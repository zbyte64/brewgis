{#
    Core Increment Model — Scenario Builder Delta

    Computes the delta between the end-state allocation and the existing
    (base canvas) condition for each attribute. This shows the change
    from baseline for every output metric.

    Inputs (via dbt vars):
        source_schema: Schema containing source tables.
        base_canvas_table: Existing condition table (must match end_state schema).
        target_schema: Schema for output.
        scenario_id: Unique scenario identifier.

    The increment is computed as:

        increment = COALESCE(end_state.value, 0) - COALESCE(base.value, 0)

    For parcel area columns, the increment preserves the sign convention
    (positive = development adds to this category).

    Output columns:
        Same attribute columns as end_state, but as deltas.
        parcel_id (from end_state)

    Materialized as: {{ var('target_schema') }}.increment_{{ var('scenario_id') }}
#}

{%- set source_schema = var('source_schema') -%}
{%- set base_canvas = var('base_canvas_table', 'base_canvas') -%}
{%- set target_schema = var('target_schema') -%}
{%- set scenario_id = var('scenario_id') -%}

WITH end_state AS (
    SELECT * FROM {{ target_schema }}.end_state_{{ scenario_id }}
),
base AS (
    SELECT * FROM {{ source_schema }}.{{ base_canvas }}
)

SELECT
    -- Parcel ID for joining
    COALESCE(es.parcel_id, b.parcel_id) AS parcel_id,

    -- Base acres (from base canvas, same for all scenarios)
    b.gross_acres AS gross_acres,
    es.acres_developable,
    es.acres_developed,

    -- Population & Households deltas
    COALESCE(es.population, 0.0) - COALESCE(b.population, 0.0) AS population,
    COALESCE(es.households, 0.0) - COALESCE(b.households, 0.0) AS households,

    -- Dwelling unit deltas
    COALESCE(es.dwelling_units_total, 0.0) - COALESCE(b.dwelling_units_total, 0.0) AS dwelling_units_total,
    COALESCE(es.dwelling_units_sf_ll, 0.0) - COALESCE(b.dwelling_units_sf_ll, 0.0) AS dwelling_units_sf_ll,
    COALESCE(es.dwelling_units_sf_sl, 0.0) - COALESCE(b.dwelling_units_sf_sl, 0.0) AS dwelling_units_sf_sl,
    COALESCE(es.dwelling_units_attached_sf, 0.0) - COALESCE(b.dwelling_units_attached_sf, 0.0) AS dwelling_units_attached_sf,
    COALESCE(es.dwelling_units_mf_2_4, 0.0) - COALESCE(b.dwelling_units_mf_2_4, 0.0) AS dwelling_units_mf_2_4,
    COALESCE(es.dwelling_units_mf_5p, 0.0) - COALESCE(b.dwelling_units_mf_5p, 0.0) AS dwelling_units_mf_5p,

    -- Employment deltas
    COALESCE(es.employment_total, 0.0) - COALESCE(b.employment_total, 0.0) AS employment_total,

    -- Building square footage deltas
    COALESCE(es.building_sqft_total, 0.0) - COALESCE(b.building_sqft_total, 0.0) AS building_sqft_total,
    COALESCE(es.building_sqft_residential, 0.0) - COALESCE(b.building_sqft_residential, 0.0) AS building_sqft_residential,
    COALESCE(es.building_sqft_commercial, 0.0) - COALESCE(b.building_sqft_commercial, 0.0) AS building_sqft_commercial,
    COALESCE(es.building_sqft_office, 0.0) - COALESCE(b.building_sqft_office, 0.0) AS building_sqft_office,
    COALESCE(es.building_sqft_industrial, 0.0) - COALESCE(b.building_sqft_industrial, 0.0) AS building_sqft_industrial,
    COALESCE(es.building_sqft_public, 0.0) - COALESCE(b.building_sqft_public, 0.0) AS building_sqft_public,
    COALESCE(es.building_sqft_retail, 0.0) - COALESCE(b.building_sqft_retail, 0.0) AS building_sqft_retail,
    COALESCE(es.building_sqft_wholesale, 0.0) - COALESCE(b.building_sqft_wholesale, 0.0) AS building_sqft_wholesale,
    COALESCE(es.building_sqft_education, 0.0) - COALESCE(b.building_sqft_education, 0.0) AS building_sqft_education,
    COALESCE(es.building_sqft_healthcare, 0.0) - COALESCE(b.building_sqft_healthcare, 0.0) AS building_sqft_healthcare,
    COALESCE(es.building_sqft_hotel_lodging, 0.0) - COALESCE(b.building_sqft_hotel_lodging, 0.0) AS building_sqft_hotel_lodging,
    COALESCE(es.building_sqft_entertainment, 0.0) - COALESCE(b.building_sqft_entertainment, 0.0) AS building_sqft_entertainment,
    COALESCE(es.building_sqft_other, 0.0) - COALESCE(b.building_sqft_other, 0.0) AS building_sqft_other,

    -- Water deltas
    COALESCE(es.res_irrigated_sqft, 0.0) - COALESCE(b.res_irrigated_sqft, 0.0) AS res_irrigated_sqft,
    COALESCE(es.com_irrigated_sqft, 0.0) - COALESCE(b.com_irrigated_sqft, 0.0) AS com_irrigated_sqft,

    -- Parcel acres deltas
    COALESCE(es.parcel_acres_developed, 0.0) - COALESCE(b.parcel_acres_developed, 0.0) AS parcel_acres_developed,
    COALESCE(es.parcel_acres_agriculture, 0.0) - COALESCE(b.parcel_acres_agriculture, 0.0) AS parcel_acres_agriculture,
    COALESCE(es.parcel_acres_open_space, 0.0) - COALESCE(b.parcel_acres_open_space, 0.0) AS parcel_acres_open_space,
    COALESCE(es.parcel_acres_vacant, 0.0) - COALESCE(b.parcel_acres_vacant, 0.0) AS parcel_acres_vacant,

    -- Network deltas
    COALESCE(es.intersection_density, 0.0) - COALESCE(b.intersection_density, 0.0) AS intersection_density,

    -- Land development category (from end state, not a delta)
    es.land_dev_category,

    -- Geometry (from end state — use base if no end state)
    COALESCE(es.geom, b.geom) AS geom
FROM end_state es
FULL OUTER JOIN base b ON es.parcel_id = b.parcel_id

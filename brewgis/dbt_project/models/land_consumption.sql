{#
    Land Consumption Model — L1 (Land Use Change) + L2 (Impervious Surface)

    L1: Classifies land use transitions and computes acres consumed by
        development type for each parcel with a built form assignment.

    L2: Estimates impervious surface change from building footprints,
        parking, and right-of-way (ROW) infrastructure.

    Inputs (via dbt vars):
        target_schema: Schema for output.
        scenario_id: Unique scenario identifier.
        parking_per_unit: Parking spaces per dwelling unit (default: 0.5).
        parking_per_employee: Parking spaces per employee (default: 0.2).
        ground_coverage_factor: Building-to-ground coverage ratio (default: 0.6).
        parking_space_sqft: Square feet per parking space (default: 300).
        row_fraction: ROW as fraction of developed acres (default: 0.15).

    Source table: {{ var('target_schema') }}.end_state_{{ var('scenario_id') }}

    Output columns:
        parcel_id, land_use_transition, acres_consumed, acres_preserved,
        development_type,
        impervious_sqft, impervious_acres, pervious_acres, impervious_pct,
        geom

    Materialized as: {{ var('target_schema') }}.land_consumption_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='land_consumption_' ~ scenario_id) }}

{%- set parking_per_unit = var('parking_per_unit', 0.5) -%}
{%- set parking_per_employee = var('parking_per_employee', 0.2) -%}
{%- set ground_coverage_factor = var('ground_coverage_factor', 0.6) -%}
{%- set parking_space_sqft = var('parking_space_sqft', 300) -%}
{%- set row_fraction = var('row_fraction', 0.15) -%}

WITH parcel_data AS (
    SELECT
        es.parcel_id,
        es.gross_acres,
        es.acres_developed,
        es.building_sqft_total,
        es.dwelling_units_total,
        es.employment_total,
        es.land_dev_category,
        es.built_form_id,
        es.parcel_acres_developed,
        es.parcel_acres_agriculture,
        es.parcel_acres_open_space,
        es.parcel_acres_vacant,
        es.geom
    FROM {{ var('target_schema') }}.end_state_{{ var('scenario_id') }} AS es
),

-- L1: Land use change classification
land_use AS (
    SELECT
        parcel_id,
        gross_acres,
        acres_developed,
        -- Classify land use transition
        CASE
            WHEN built_form_id IS NOT NULL AND acres_developed > 0 THEN
                CASE
                    WHEN land_dev_category = 'urban' THEN 'vacant_to_urban'
                    WHEN land_dev_category = 'compact' THEN 'vacant_to_compact'
                    WHEN land_dev_category = 'standard' THEN 'vacant_to_standard'
                    WHEN land_dev_category = 'rural' THEN 'vacant_to_rural'
                    ELSE 'vacant_to_developed'
                END
            ELSE 'unchanged'
        END AS land_use_transition,
        -- Acres consumed by this development
        CASE
            WHEN built_form_id IS NOT NULL AND acres_developed > 0
                THEN acres_developed
            ELSE 0.0
        END AS acres_consumed,
        -- Acres preserved (not developed)
        CASE
            WHEN built_form_id IS NOT NULL AND acres_developed > 0
                THEN GREATEST(gross_acres - acres_developed, 0.0)
            ELSE gross_acres
        END AS acres_preserved,
        COALESCE(land_dev_category, 'undeveloped') AS development_type,
        building_sqft_total,
        dwelling_units_total,
        employment_total,
        parcel_acres_developed,
        geom
    FROM parcel_data
),

-- L2: Impervious surface estimation
impervious AS (
    SELECT
        parcel_id,
        -- Building footprint: building_sqft_total × ground_coverage_factor
        COALESCE(building_sqft_total * {{ ground_coverage_factor }}, 0.0) AS building_footprint_sqft,
        -- Parking: (DU × spaces/DU + employment × spaces/employee) × sqft/space
        COALESCE(
            (dwelling_units_total * {{ parking_per_unit }}
             + employment_total * {{ parking_per_employee }})
            * {{ parking_space_sqft }},
            0.0
        ) AS parking_sqft,
        -- ROW: developed acres × fraction (converted to sqft)
        COALESCE(
            acres_developed * {{ row_fraction }} * 43560.0,
            0.0
        ) AS row_sqft,
        geom
    FROM land_use
)

SELECT
    lu.parcel_id,
    lu.land_use_transition,
    lu.acres_consumed,
    lu.acres_preserved,
    lu.development_type,
    -- L2 impervious surface outputs
    COALESCE(imp.building_footprint_sqft, 0.0)
        + COALESCE(imp.parking_sqft, 0.0)
        + COALESCE(imp.row_sqft, 0.0)
    AS impervious_sqft,
    (COALESCE(imp.building_footprint_sqft, 0.0)
        + COALESCE(imp.parking_sqft, 0.0)
        + COALESCE(imp.row_sqft, 0.0)) / 43560.0
    AS impervious_acres,
    CASE
        WHEN lu.gross_acres > 0
            THEN GREATEST(
                lu.gross_acres
                - (COALESCE(imp.building_footprint_sqft, 0.0)
                    + COALESCE(imp.parking_sqft, 0.0)
                    + COALESCE(imp.row_sqft, 0.0)) / 43560.0,
                0.0
            )
        ELSE 0.0
    END AS pervious_acres,
    CASE
        WHEN lu.gross_acres > 0
            THEN ((COALESCE(imp.building_footprint_sqft, 0.0)
                + COALESCE(imp.parking_sqft, 0.0)
                + COALESCE(imp.row_sqft, 0.0)) / 43560.0)
                / lu.gross_acres * 100.0
        ELSE 0.0
    END AS impervious_pct,
    lu.geom
FROM land_use AS lu
LEFT JOIN impervious AS imp USING (parcel_id)

{#
    Dasymetric Weights — per-parcel population and employment weights.

    Merges assessor parcel geometries with sales building data, estimates building
    sqft for parcels without sales records using land-use-type medians, and computes
    ``pop_dasym_weight`` and ``emp_dasym_weight`` per parcel.

    Weight formulas:
        pop_dasym_weight = pop_mult * COALESCE(
            actual_living_sqft,        -- from sales data (55K parcels)
            estimated_living_sqft,     -- land-use-type median × size ratio
            lotsize * impervious_fraction,  -- NLCD-adjusted (when available)
            lotsize                    -- raw area fallback
        )

        emp_dasym_weight = emp_mult * COALESCE(
            actual_building_sqft,
            estimated_building_sqft,
            lotsize * impervious_fraction,
            lotsize
        ) * (1.0 + COALESCE(intersection_density, 0.0) / 200.0)

    Optional dependencies (controlled by dbt vars):
        - ``nlcd_parcel_table``: adds ``impervious_fraction`` from NLCD zonal stats
        - ``osm_intersection_table``: adds ``intersection_density`` from OSM

    Dasymetric multiplier seed table: ``{{ ref('dasymetric_weights') }}``

    Materialized as: table
#}

{{ config(materialized='table',
    indexes=[
        {'columns': ['parcel_id'], 'unique': True},
        {'columns': ['geometry'], 'type': 'gist'},
    ])
}}

{%- set nlcd_table = var('nlcd_parcel_table', none) -%}
{%- set osm_table = var('osm_intersection_table', none) -%}

WITH assessor_parcels AS (
    SELECT
        parcel_id,
        geometry,
        COALESCE(NULLIF(lot_size_acres, 0), 0.01) AS lot_size_acres
    FROM {{ ref('sacog_assessor_parcels') }}
),

sales_data AS (
    SELECT
        parcel_id,
        living_area AS actual_living_sqft,
        building_sf AS actual_building_sqft,
        property_type
    FROM {{ ref('sacog_assessor_sales') }}
    WHERE living_area IS NOT NULL OR building_sf IS NOT NULL
),

-- Per-property-type median building sizes from sales data
building_medians AS (
    SELECT
        property_type,
        parcel_count,
        median_living_area,
        median_building_sf,
        median_lot_size_acres
    FROM {{ ref('assessor_building_medians') }}
),

-- Estimate building sqft for parcels without sales data

-- Use median from the most-represented property type as best estimate
estimated AS (
    SELECT * FROM (
    SELECT
        ap.parcel_id,
        ap.lot_size_acres,
        bm.median_living_area,
        bm.median_building_sf,
        bm.median_lot_size_acres,
        CASE
            WHEN bm.median_living_area IS NOT NULL AND bm.median_lot_size_acres > 0
            THEN bm.median_living_area * (ap.lot_size_acres / bm.median_lot_size_acres)
            ELSE NULL
        END AS estimated_living_sqft,
        CASE
            WHEN bm.median_building_sf IS NOT NULL AND bm.median_lot_size_acres > 0
            THEN bm.median_building_sf * (ap.lot_size_acres / bm.median_lot_size_acres)
            ELSE NULL
            END AS estimated_building_sqft,
            ROW_NUMBER() OVER (
                PARTITION BY ap.parcel_id ORDER BY bm.parcel_count DESC
            ) AS rn
    FROM assessor_parcels ap
        LEFT JOIN building_medians bm ON TRUE
    ) sub
    WHERE rn = 1
),

-- Classify parcels into land_development_category
-- Maps 2-digit assessor land use code to category via assessor_use_codes seed
classified AS (
    SELECT
        ap.parcel_id,
        ap.lot_size_acres,
        COALESCE(auc.category, 'urban') AS land_development_category
    FROM assessor_parcels ap
    LEFT JOIN {{ ref('sacog_assessor_parcels') }} sap
        ON ap.parcel_id = sap.parcel_id
    LEFT JOIN {{ ref('assessor_use_codes') }} auc
        ON LEFT(COALESCE(sap.landuse, ''), 2) = auc.use_code::text
),

-- Join NLCD impervious fraction (optional)
nlcd_join AS (
    SELECT
        ap.parcel_id,
        {% if nlcd_table %}
        nlcd.impervious_fraction
        {% else %}
        NULL::double precision AS impervious_fraction
        {% endif %}
    FROM assessor_parcels ap
    {% if nlcd_table %}
    LEFT JOIN {{ nlcd_table }} nlcd
        ON ap.parcel_id = nlcd.parcel_id
    {% endif %}
),

-- Join OSM intersection density (optional)
osm_join AS (
    SELECT
        ap.parcel_id,
        {% if osm_table %}
        osm.intersection_density
        {% else %}
        NULL::double precision AS intersection_density
        {% endif %}
    FROM assessor_parcels ap
    {% if osm_table %}
    LEFT JOIN {{ osm_table }} osm
        ON ap.parcel_id = osm.parcel_id
    {% endif %}
),

-- Assemble final dasymetric weights
assembled AS (
    SELECT
        ap.parcel_id,
        ap.geometry,
        ap.lot_size_acres,
        cl.land_development_category,
        -- Actual building sqft from sales data (best)
        sd.actual_living_sqft,
        sd.actual_building_sqft,
        -- Estimated building sqft from land-use medians (good)
        est.estimated_living_sqft,
        est.estimated_building_sqft,
        -- NLCD impervious fraction (decent)
        nj.impervious_fraction,
        -- OSM intersection density (small boost to employment)
        oj.intersection_density,
        -- Dasymetric multipliers
        dw.pop_mult,
        dw.emp_mult
    FROM assessor_parcels ap
    LEFT JOIN classified cl ON ap.parcel_id = cl.parcel_id
    LEFT JOIN sales_data sd ON ap.parcel_id = sd.parcel_id
    LEFT JOIN estimated est ON ap.parcel_id = est.parcel_id
    LEFT JOIN nlcd_join nj ON ap.parcel_id = nj.parcel_id
    LEFT JOIN osm_join oj ON ap.parcel_id = oj.parcel_id
    LEFT JOIN {{ ref('dasymetric_weights') }} dw
        ON cl.land_development_category = dw.land_development_category
)

SELECT
    parcel_id,
    geometry,
    lot_size_acres,
    land_development_category,
    actual_living_sqft,
    actual_building_sqft,
    estimated_living_sqft,
    estimated_building_sqft,
    impervious_fraction,
    intersection_density,
    -- Population weight
    COALESCE(pop_mult, 1.0) * COALESCE(
        actual_living_sqft,
        estimated_living_sqft,
        lot_size_acres * COALESCE(impervious_fraction, 1.0),
        lot_size_acres
    ) AS pop_dasym_weight,
    -- Employment weight with OSM boost
    COALESCE(emp_mult, 0.15) * COALESCE(
        actual_building_sqft,
        estimated_building_sqft,
        lot_size_acres * COALESCE(impervious_fraction, 1.0),
        lot_size_acres
    ) * (1.0 + COALESCE(intersection_density, 0.0) / 200.0) AS emp_dasym_weight
FROM assembled

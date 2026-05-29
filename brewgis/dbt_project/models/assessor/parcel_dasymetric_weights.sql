{#
    Dasymetric Weights — per-parcel population and employment weights.

    Merges assessor parcel geometries with sales building data, estimates building
    sqft for parcels without sales records using land-use-type medians, and computes
    ``pop_dasym_weight`` and ``emp_dasym_weight`` per parcel.

    Also computes ``du_subtype`` (assessor-based dwelling unit sub-type
    classification) and ``du_dasym_weight`` (dasymetric weight for DU
    sub-type allocation, based on assessor ``units``).

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
        actual_living_sqft,
        actual_building_sqft,
        property_type,
        lot_size_acres,
        units
    FROM (
        SELECT
            parcel_id,
            living_area AS actual_living_sqft,
            building_sf AS actual_building_sqft,
            property_type,
            lot_size_acres,
            units,
            -- Prefer rows with both living_area and building_sf, then the most
            -- complete, then the most recent (year_built descending).
            ROW_NUMBER() OVER (
                PARTITION BY parcel_id
                ORDER BY
                    CASE
                        WHEN living_area IS NOT NULL AND building_sf IS NOT NULL THEN 0
                        WHEN living_area IS NOT NULL THEN 1
                        WHEN building_sf IS NOT NULL THEN 2
                        ELSE 3
                    END,
                    year_built DESC NULLS LAST
            ) AS rn
        FROM {{ ref('sacog_assessor_sales') }}
        WHERE living_area IS NOT NULL OR building_sf IS NOT NULL
    ) deduped_sales
    WHERE rn = 1
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
        ON LEFT(COALESCE(sap.landuse::text, ''), 2) = auc.use_code::text
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
        dw.emp_mult,
        -- Assessor sales data for DU classification
        sd.property_type,
        sd.lot_size_acres AS sales_lot_size_acres,
        sd.units
    FROM assessor_parcels ap
    LEFT JOIN classified cl ON ap.parcel_id = cl.parcel_id
    LEFT JOIN sales_data sd ON ap.parcel_id = sd.parcel_id
    LEFT JOIN estimated est ON ap.parcel_id = est.parcel_id
    LEFT JOIN nlcd_join nj ON ap.parcel_id = nj.parcel_id
    LEFT JOIN osm_join oj ON ap.parcel_id = oj.parcel_id
    LEFT JOIN {{ ref('dasymetric_weights') }} dw
        ON cl.land_development_category = dw.land_development_category
)
,

-- DU sub-type classification from assessor sales data
-- Maps property_type + units + lot_size to DU sub-type based on actual parcel characteristics.
-- NULL when assessor data is unavailable (falls through to area-proportional allocation).
du_classification AS (
    SELECT
        parcel_id,
        CASE
            -- SFR: split by lot size (threshold ~0.15 acres = ~6,534 sqft)
            WHEN property_type = 'SFR' AND COALESCE(sales_lot_size_acres, lot_size_acres) < 0.15 THEN 'detsf_sl'
            WHEN property_type = 'SFR' AND COALESCE(sales_lot_size_acres, lot_size_acres) >= 0.15 THEN 'detsf_ll'
            -- Condo → attsf
            WHEN property_type = 'Condo' THEN 'attsf'
            -- MF: split by unit count
            WHEN property_type = 'MF' AND COALESCE(units, 0) BETWEEN 2 AND 4 THEN 'mf2to4'
            WHEN property_type = 'MF' AND COALESCE(units, 0) >= 5 THEN 'mf5p'
            -- Parcels without sales data or non-residential: NULL
            ELSE NULL
        END AS du_subtype,
        -- DU dasymetric weight: actual units when available, 1.0 fallback
        COALESCE(NULLIF(units, 0), 1)::double precision AS du_dasym_weight
    FROM assembled
)

SELECT
    a.parcel_id,
    a.geometry,
    a.lot_size_acres,
    a.land_development_category,
    a.actual_living_sqft,
    a.actual_building_sqft,
    a.estimated_living_sqft,
    a.estimated_building_sqft,
    a.impervious_fraction,
    a.intersection_density,
    -- Population weight
    COALESCE(a.pop_mult, 1.0) * COALESCE(
        a.actual_living_sqft,
        a.estimated_living_sqft,
        a.lot_size_acres * COALESCE(a.impervious_fraction, 1.0),
        a.lot_size_acres
    ) AS pop_dasym_weight,
    -- Employment weight with OSM boost
    COALESCE(a.emp_mult, 0.15) * COALESCE(
        a.actual_building_sqft,
        a.estimated_building_sqft,
        a.lot_size_acres * COALESCE(a.impervious_fraction, 1.0),
        a.lot_size_acres
    ) * (1.0 + COALESCE(a.intersection_density, 0.0) / 200.0) AS emp_dasym_weight,
    -- DU sub-type and weight from assessor data
    dc.du_subtype,
    dc.du_dasym_weight
FROM assembled a
LEFT JOIN du_classification dc ON a.parcel_id = dc.parcel_id

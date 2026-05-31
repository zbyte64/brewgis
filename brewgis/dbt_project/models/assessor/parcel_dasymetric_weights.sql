{#
    Dasymetric Weights — per-parcel population and employment weights.

    Merges assessor parcel geometries with sales building data, estimates building
    sqft for parcels without sales records using land-use-type medians, and computes
    ``pop_dasym_weight`` and ``emp_dasym_weight`` per parcel.

    Also computes ``du_subtype`` (assessor-based dwelling unit sub-type
    classification) and ``du_dasym_weight`` (dasymetric weight for DU
    sub-type allocation, based on assessor ``units``).

    Identifier convention:
        apn         — assessor parcel number (TEXT, e.g. "001-0234-005")
        parcel_id   — SACOG geography_id (INT4) — NOT used in this model

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
          (spatial join via ST_Intersects on geometry)
        - ``osm_intersection_table``: adds ``intersection_density`` from OSM
          (spatial join via ST_Intersects on geometry)

    Dasymetric multiplier seed table: ``{{ ref('dasymetric_weights') }}``

    Materialized as: table
#}

{{ config(materialized='table',
    indexes=[
        {'columns': ['apn'], 'unique': True},
        {'columns': ['geometry'], 'type': 'gist'},
    ])
}}

{%- set nlcd_table = var('nlcd_parcel_table', none) -%}
{%- set osm_table = var('osm_intersection_table', none) -%}

WITH assessor_parcels AS (
    SELECT
        apn,
        geometry,
        COALESCE(NULLIF(lot_size_acres, 0), 0.01) AS lot_size_acres
    FROM {{ ref('sacog_assessor_parcels') }}
),

sales_data AS (
    SELECT
        apn,
        actual_living_sqft,
        actual_building_sqft,
        property_type,
        lot_size_acres,
        units
    FROM (
        SELECT
            apn,
            living_area AS actual_living_sqft,
            building_sf AS actual_building_sqft,
            property_type,
            lot_size_acres,
            units,
            -- Prefer rows with both living_area and building_sf, then the most
            -- complete, then the most recent (year_built descending).
            ROW_NUMBER() OVER (
                PARTITION BY apn
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

estimated AS (
    SELECT * FROM (
    SELECT
        ap.apn,
        ap.lot_size_acres,
        bm.median_living_area,
        bm.median_building_sf,
        bm.median_lot_size_acres,
        CASE
            WHEN bm.median_living_area IS NOT NULL AND bm.median_lot_size_acres > 0
            THEN bm.median_living_area * (ap.lot_size_acres / bm.median_lot_size_acres)
            WHEN bm.median_living_area IS NOT NULL
            THEN bm.median_living_area
            ELSE NULL
        END AS estimated_living_sqft,
        CASE
            WHEN bm.median_building_sf IS NOT NULL AND bm.median_lot_size_acres > 0
            THEN bm.median_building_sf * (ap.lot_size_acres / bm.median_lot_size_acres)
            WHEN bm.median_building_sf IS NOT NULL
            THEN bm.median_building_sf
            ELSE NULL
        END AS estimated_building_sqft,
            ROW_NUMBER() OVER (
                PARTITION BY ap.apn ORDER BY bm.parcel_count DESC
            ) AS rn
    FROM assessor_parcels ap
        LEFT JOIN building_medians bm ON TRUE
    ) sub
    WHERE rn = 1
),


classified AS (
    SELECT
        ap.apn,
        ap.lot_size_acres,
        COALESCE(auc.category, 'urban') AS land_development_category
    FROM assessor_parcels ap
    LEFT JOIN {{ ref('sacog_assessor_parcels') }} sap
        ON ap.apn = sap.apn
    LEFT JOIN {{ ref('assessor_use_codes') }} auc
        ON LEFT(COALESCE(sap.landuse::text, ''), 2) = auc.use_code::text
),

-- Join NLCD impervious fraction via spatial intersection (optional)
{% if nlcd_table %}
nlcd_join AS (
    SELECT DISTINCT ON (ap.apn)
        ap.apn,
        nlcd.impervious_fraction
    FROM assessor_parcels ap
    LEFT JOIN {{ nlcd_table }} nlcd
        ON ST_Intersects(ap.geometry, nlcd.geometry)
    ORDER BY ap.apn,
        ST_Area(ST_Intersection(ap.geometry, nlcd.geometry)) DESC NULLS LAST
),
{% else %}
nlcd_join AS (
    SELECT ap.apn, NULL::double precision AS impervious_fraction
    FROM assessor_parcels ap
),
{% endif %}

-- Join OSM intersection density via spatial intersection (optional)
{% if osm_table %}
osm_join AS (
    SELECT DISTINCT ON (ap.apn)
        ap.apn,
        osm.intersection_density
    FROM assessor_parcels ap
    LEFT JOIN {{ osm_table }} osm
        ON ST_Intersects(ap.geometry, osm.geometry)
    ORDER BY ap.apn,
        ST_Area(ST_Intersection(ap.geometry, osm.geometry)) DESC NULLS LAST
),
{% else %}
osm_join AS (
    SELECT ap.apn, NULL::double precision AS intersection_density
    FROM assessor_parcels ap
),
{% endif %}

-- Assemble final dasymetric weights
assembled AS (
    SELECT
        ap.apn,
        ap.geometry,
        ap.lot_size_acres,
        cl.land_development_category,
        -- Actual building sqft from sales data (best)
        sd.actual_living_sqft,
        sd.actual_building_sqft,
        -- Estimated building sqft from land-use medians (good)
        est.estimated_living_sqft,
        est.estimated_building_sqft,
        -- Footprint-imputed building sqft (good, via KNN)
        fi.imputed_living_sqft AS footprint_imputed_living_sqft,
        fi.imputed_building_sqft AS footprint_imputed_building_sqft,
        fi.imputed_units AS footprint_imputed_units,
        fi.imputed_property_type AS footprint_imputed_property_type,
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
    LEFT JOIN classified cl ON ap.apn = cl.apn
    LEFT JOIN sales_data sd ON ap.apn = sd.apn
    LEFT JOIN estimated est ON ap.apn = est.apn
    LEFT JOIN {{ ref('parcel_footprint_imputed') }} fi ON ap.apn = fi.apn
    LEFT JOIN nlcd_join nj ON ap.apn = nj.apn
    LEFT JOIN osm_join oj ON ap.apn = oj.apn
    LEFT JOIN {{ ref('dasymetric_weights') }} dw
        ON cl.land_development_category = dw.land_development_category
)
,

-- DU sub-type classification from assessor sales data
-- Maps property_type + units + lot_size to DU sub-type based on actual parcel characteristics.
-- Falls back to footprint-imputed data when assessor sales data is unavailable.
-- NULL when assessor data is unavailable (falls through to area-proportional allocation).
du_classification AS (
    SELECT
        apn,
        CASE
            -- Assessor-based classification (when sales data available)
            -- SFR: split by lot size (threshold ~0.15 acres = ~6,534 sqft)
            WHEN (property_type IN ('SFR', 'Single Family Residence') OR property_type LIKE 'Single Family%')
                AND COALESCE(sales_lot_size_acres, lot_size_acres) < 0.15 THEN 'detsf_sl'
            WHEN (property_type IN ('SFR', 'Single Family Residence') OR property_type LIKE 'Single Family%')
                AND COALESCE(sales_lot_size_acres, lot_size_acres) >= 0.15 THEN 'detsf_ll'
            -- Condo → attsf
            WHEN property_type IN ('Condo', 'Condominium') THEN 'attsf'
            -- MF: split by unit count
            WHEN (property_type IN ('MF', 'Multiple Family Residence') OR property_type LIKE 'Multiple Family%')
                AND COALESCE(units, 0) BETWEEN 2 AND 4 THEN 'mf2to4'
            WHEN (property_type IN ('MF', 'Multiple Family Residence') OR property_type LIKE 'Multiple Family%')
                AND COALESCE(units, 0) >= 5 THEN 'mf5p'
            -- Footprint-imputed classification (when sales data unavailable)
            WHEN footprint_imputed_property_type IN ('Single Family Residence')
                AND COALESCE(sales_lot_size_acres, lot_size_acres) < 0.15 THEN 'detsf_sl'
            WHEN footprint_imputed_property_type IN ('Single Family Residence')
                AND COALESCE(sales_lot_size_acres, lot_size_acres) >= 0.15 THEN 'detsf_ll'
            WHEN footprint_imputed_property_type IN ('Condominium') THEN 'attsf'
            WHEN footprint_imputed_property_type IN ('Multiple Family Residence')
                AND COALESCE(footprint_imputed_units, 0) BETWEEN 2 AND 4 THEN 'mf2to4'
            WHEN footprint_imputed_property_type IN ('Multiple Family Residence')
                AND COALESCE(footprint_imputed_units, 0) >= 5 THEN 'mf5p'
            -- Parcels without sales data or non-residential: NULL
            ELSE NULL
        END AS du_subtype,
        -- DU dasymetric weight: actual units when available, 1.0 fallback
        COALESCE(
            NULLIF(units, 0),
            NULLIF(footprint_imputed_units, 0),
            1
        )::double precision AS du_dasym_weight
    FROM assembled
)

SELECT
    a.apn,
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
        a.footprint_imputed_living_sqft,
        a.estimated_living_sqft,
        a.lot_size_acres * COALESCE(a.impervious_fraction, 1.0),
        a.lot_size_acres
    ) AS pop_dasym_weight,
    -- Employment weight with OSM boost
    COALESCE(a.emp_mult, 0.15) * COALESCE(
        a.actual_building_sqft,
        a.footprint_imputed_building_sqft,
        a.estimated_building_sqft,
        a.lot_size_acres * COALESCE(a.impervious_fraction, 1.0),
        a.lot_size_acres
    ) * (1.0 + COALESCE(a.intersection_density, 0.0) / 200.0) AS emp_dasym_weight,
    -- DU sub-type and weight from assessor data
    dc.du_subtype,
    dc.du_dasym_weight
FROM assembled a
LEFT JOIN du_classification dc ON a.apn = dc.apn

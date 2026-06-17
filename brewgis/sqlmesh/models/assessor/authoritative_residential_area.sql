MODEL (
  name brewgis.assessor.authoritative_residential_area,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  )
);

-- Authoritative Residential Area — per-parcel authoritative residential and
-- non-residential building area from observational data only.
--
-- This is a pass-through model that consolidates Overture building footprints,
-- assessor sales data, and k-NN imputed values into ONE authoritative value
-- per parcel. No statistical mixing, no ACS population data, no weighting.
--
-- Priority order:
--   1. Overture building footprint area × max_levels
--   2. Overture building footprint area (flat, no level multiplier)
--   3. Assessor sales (ground truth living/building area)
--   4. Footprint-imputed (k-NN from similar parcels)
--
-- For parcels straddling two observation regimes: COALESCE picks the first
-- non-null. The parcel is atomic — it gets the total of all buildings on it.
-- NULL output means "no authoritative data available" and the downstream
-- dasymetric weight falls through to estimates (lot-size proxies).

WITH parcel_base AS (
    SELECT
        pbf.apn,
        pbf.geometry,
        pbf.lot_size_acres,
        pbf.residential_building_sqft,
        pbf.non_residential_building_sqft,
        pbf.residential_building_count,
        pbf.non_residential_building_count,
        pbf.max_levels
    FROM brewgis.assessor.parcel_building_footprints pbf
),

-- Deduplicated assessor sales data (same logic as parcel_dasymetric_weights)
sales_data AS (
    SELECT
        apn,
        living_area AS actual_living_sqft,
        building_sf AS actual_building_sqft
    FROM (
        SELECT
            apn,
            living_area,
            building_sf,
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
        FROM public.sacog_assessor_sales_raw
        WHERE living_area IS NOT NULL OR building_sf IS NOT NULL
    ) deduped_sales
    WHERE rn = 1
),

-- k-NN imputed values from parcel_footprint_imputed
footprint_imputed AS (
    SELECT
        apn,
        imputed_living_sqft AS footprint_imputed_living_sqft,
        imputed_building_sqft AS footprint_imputed_building_sqft
    FROM brewgis.assessor.parcel_footprint_imputed
),

assembled AS (
    SELECT
        pb.apn,
        pb.geometry,
        pb.residential_building_sqft,
        pb.non_residential_building_sqft,
        pb.residential_building_count,
        pb.non_residential_building_count,
        pb.max_levels,
        sd.actual_living_sqft,
        sd.actual_building_sqft,
        fi.footprint_imputed_living_sqft,
        fi.footprint_imputed_building_sqft
    FROM parcel_base pb
    LEFT JOIN sales_data sd ON pb.apn = sd.apn
    LEFT JOIN footprint_imputed fi ON pb.apn = fi.apn
)

SELECT
    apn,
    geometry,
    -- Authoritative residential building area (floor area, not footprint)
    CASE
        WHEN residential_building_sqft > 0
             AND COALESCE(max_levels, 0) > 0
        THEN residential_building_sqft * max_levels
        WHEN residential_building_sqft > 0
        THEN residential_building_sqft
        WHEN COALESCE(actual_living_sqft, 0) > 0
        THEN actual_living_sqft
        WHEN COALESCE(footprint_imputed_living_sqft, 0) > 0
        THEN footprint_imputed_living_sqft
        ELSE NULL
    END AS authoritative_residential_sqft,
    -- Authoritative non-residential building area (floor area, not footprint)
    CASE
        WHEN non_residential_building_sqft > 0
             AND COALESCE(max_levels, 0) > 0
        THEN non_residential_building_sqft * max_levels
        WHEN non_residential_building_sqft > 0
        THEN non_residential_building_sqft
        WHEN COALESCE(actual_building_sqft, 0) > 0
             AND COALESCE(actual_living_sqft, 0) > 0
        THEN actual_building_sqft - actual_living_sqft
        WHEN COALESCE(actual_building_sqft, 0) > 0
        THEN actual_building_sqft
        WHEN COALESCE(footprint_imputed_building_sqft, 0) > 0
             AND COALESCE(footprint_imputed_living_sqft, 0) > 0
        THEN footprint_imputed_building_sqft - footprint_imputed_living_sqft
        WHEN COALESCE(footprint_imputed_building_sqft, 0) > 0
        THEN footprint_imputed_building_sqft
        ELSE NULL
    END AS authoritative_non_residential_sqft,
    -- Data source indicator: which priority tier was used for residential
    CASE
        WHEN residential_building_sqft > 0
             AND COALESCE(max_levels, 0) > 0
        THEN 'overture_with_levels'
        WHEN residential_building_sqft > 0
        THEN 'overture_flat'
        WHEN COALESCE(actual_living_sqft, 0) > 0
        THEN 'assessor_sales'
        WHEN COALESCE(footprint_imputed_living_sqft, 0) > 0
        THEN 'footprint_imputed'
        ELSE NULL
    END AS data_source,
    residential_building_sqft,
    non_residential_building_sqft,
    residential_building_count,
    non_residential_building_count,
    max_levels,
    actual_living_sqft,
    actual_building_sqft,
    footprint_imputed_living_sqft,
    footprint_imputed_building_sqft
FROM assembled;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_authoritative_residential_area_apn
  ON brewgis.assessor.authoritative_residential_area (apn)
);
ANALYZE brewgis.assessor.authoritative_residential_area;

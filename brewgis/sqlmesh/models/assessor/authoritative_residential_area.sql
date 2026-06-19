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

WITH sales_data AS (
    -- Deduplicated assessor sales data, filtered to APNs that have building
    -- footprints to avoid sorting irrelevant rows.
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
        WHERE (living_area IS NOT NULL OR building_sf IS NOT NULL)
          AND apn IN (SELECT apn FROM brewgis.assessor.parcel_building_footprints)
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
        pbf.apn,
        pbf.residential_building_sqft,
        pbf.non_residential_building_sqft,
        pbf.max_levels,
        sd.actual_living_sqft,
        sd.actual_building_sqft,
        fi.footprint_imputed_living_sqft,
        fi.footprint_imputed_building_sqft
    FROM brewgis.assessor.parcel_building_footprints pbf
    LEFT JOIN sales_data sd ON pbf.apn = sd.apn
    LEFT JOIN footprint_imputed fi ON pbf.apn = fi.apn
)

SELECT
    apn,
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
    END AS authoritative_non_residential_sqft
FROM assembled;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_authoritative_residential_area_apn
  ON brewgis.assessor.authoritative_residential_area (apn);
ANALYZE brewgis.assessor.authoritative_residential_area;

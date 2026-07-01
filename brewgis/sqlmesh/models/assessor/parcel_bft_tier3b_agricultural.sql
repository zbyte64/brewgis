MODEL (
  name brewgis.assessor.parcel_bft_tier3b_agricultural,
  kind VIEW,
  audits (
    assert_bft_tier3b_footprint_filter
  )
);

-- Tier 3b: agricultural classification for large-lot parcels with minimal
-- building footprint coverage, that were not classified by KNN (Tier 3).
-- Returns one row per parcel classified as 'agricultural'.

WITH assessor_parcels AS (
    SELECT
        apn,
        COALESCE(NULLIF(lot_size_acres, 0), 0.01) AS lot_size_acres,
        landuse,
        LEFT(landuse::text, 2) AS landuse_prefix
    FROM brewgis.assessor.sacog_assessor_parcels
),
building_metrics AS (
    SELECT
        apn,
        COALESCE(footprint_ratio, 0) AS footprint_ratio
    FROM brewgis.assessor.parcel_building_sqft_by_type
),
unknown_parcels AS (
    SELECT
        ap.apn,
        ap.lot_size_acres,
        COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
        ap.landuse_prefix
    FROM assessor_parcels ap
    LEFT JOIN building_metrics bs ON ap.apn = bs.apn
    WHERE NOT EXISTS (SELECT 1 FROM brewgis.assessor.parcel_bft_tier0_landuse t0 WHERE t0.apn = ap.apn)
      AND NOT EXISTS (SELECT 1 FROM brewgis.assessor.parcel_bft_tier1_sales t1 WHERE t1.apn = ap.apn)
)
SELECT
    u.apn,
    'agricultural'::text AS built_form_key
FROM unknown_parcels u
WHERE u.lot_size_acres > 3.0
  AND COALESCE(u.footprint_ratio, 0) < 0.02
  AND ((u.landuse_prefix NOT LIKE 'A2' AND u.landuse_prefix NOT IN ('AT')) OR u.landuse_prefix IS NULL)
  AND NOT EXISTS (SELECT 1 FROM brewgis.assessor.parcel_bft_tier2_footprints t2 WHERE t2.apn = u.apn)
  AND NOT EXISTS (SELECT 1 FROM brewgis.assessor.parcel_bft_tier3_knn t3 WHERE t3.apn = u.apn);

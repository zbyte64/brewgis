MODEL (
  name brewgis.assessor.parcel_bft_tier4_catchall,
  kind VIEW,
  audits (
    assert_bft_tier4_area_heuristic
  )
);

-- Tier 4: catch-all heuristic for parcels not classified by any higher tier.
-- Uses lot size, zone, and APN parity to assign a built_form_key.
-- Returns one row per parcel successfully classified.

WITH assessor_parcels AS (
    SELECT
        apn,
        COALESCE(NULLIF(lot_size_acres, 0), 0.01) AS lot_size_acres,
        landuse,
        LEFT(landuse::text, 2) AS landuse_prefix,
        zone
    FROM brewgis.assessor.sacog_assessor_parcels
),
building_metrics AS (
    SELECT
        apn,
        COALESCE(footprint_ratio, 0) AS footprint_ratio,
        COALESCE(residential_building_sqft, 0) AS residential_building_sqft
    FROM brewgis.assessor.parcel_building_sqft_by_type
),
int_density AS (
    SELECT
        apn,
        intersection_density
    FROM brewgis.assessor.overture_intersection_density
),
unknown_parcels AS (
    SELECT
        ap.apn,
        ap.lot_size_acres,
        COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
        COALESCE(bs.residential_building_sqft, 0) AS residential_building_sqft,
        COALESCE(id.intersection_density, 0) AS intersection_density,
        ap.zone,
        ap.landuse_prefix,
        ap.landuse
    FROM assessor_parcels ap
    LEFT JOIN building_metrics bs ON ap.apn = bs.apn
    LEFT JOIN int_density id ON ap.apn = id.apn
    WHERE NOT EXISTS (SELECT 1 FROM brewgis.assessor.parcel_bft_tier0_landuse t0 WHERE t0.apn = ap.apn)
      AND NOT EXISTS (SELECT 1 FROM brewgis.assessor.parcel_bft_tier1_sales t1 WHERE t1.apn = ap.apn)
)
SELECT
    u.apn,
    CASE
        WHEN (u.landuse_prefix LIKE 'A2' OR u.landuse_prefix IN ('AT')) THEN
            CASE
                WHEN u.residential_building_sqft >= 3000 THEN 'mf5p'
                WHEN u.intersection_density >= 100 THEN 'mf5p'
                ELSE 'mf2to4'
            END
        WHEN u.lot_size_acres > 10.0 THEN 'agricultural'
        WHEN u.lot_size_acres > 3.0 THEN
            CASE
                WHEN u.zone LIKE '%A%' THEN 'agricultural'
                ELSE 'detsf_ll'
            END
        WHEN u.lot_size_acres > 0.15 THEN 'detsf_ll'
        WHEN u.lot_size_acres > 0.01 THEN 'detsf_sl'
        ELSE
            CASE (u.apn::bigint % 2)
                WHEN 0 THEN 'mf2to4'
                WHEN 1 THEN 'attsf'
            END
    END AS built_form_key
FROM unknown_parcels u
WHERE NOT EXISTS (SELECT 1 FROM brewgis.assessor.parcel_bft_tier2_footprints t2 WHERE t2.apn = u.apn)
  AND NOT EXISTS (SELECT 1 FROM brewgis.assessor.parcel_bft_tier3_knn t3 WHERE t3.apn = u.apn)
  AND NOT EXISTS (SELECT 1 FROM brewgis.assessor.parcel_bft_tier3b_agricultural t3b WHERE t3b.apn = u.apn);

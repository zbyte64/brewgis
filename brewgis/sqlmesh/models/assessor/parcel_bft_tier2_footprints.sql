MODEL (
  name brewgis.assessor.parcel_bft_tier2_footprints,
  kind VIEW,
  audits (
    assert_bft_tier2_sfr_lot_bound
  )
);

-- Tier 2: from building footprints. Returns one row per parcel successfully
-- classified by building footprint data. Only outputs (apn, built_form_key).
-- Includes both A2/AT logic and general building footprint logic.

WITH int_density AS (
    SELECT
        apn,
        intersection_density
    FROM brewgis.assessor.overture_intersection_density
),
assessor_parcels AS (
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
        COALESCE(residential_building_sqft, 0) AS residential_building_sqft,
        COALESCE(commercial_building_sqft, 0) AS commercial_building_sqft,
        COALESCE(industrial_building_sqft, 0) AS industrial_building_sqft,
        COALESCE(other_building_sqft, 0) AS other_building_sqft,
        COALESCE(total_footprint_sqft, 0) AS total_footprint_sqft,
        COALESCE(building_count, 0) AS building_count,
        COALESCE(footprint_ratio, 0) AS footprint_ratio,
        COALESCE(max_levels, 0) AS max_levels
    FROM brewgis.assessor.parcel_building_sqft_by_type
)
SELECT DISTINCT ON (ap.apn)
    ap.apn,
    CASE
        -- A2 parcels (multi-family) with building footprints → mf2to4 or mf5p
        WHEN (ap.landuse_prefix LIKE 'A2' OR ap.landuse_prefix IN ('AT'))
             AND bs.residential_building_sqft > 0
             AND (
                 COALESCE(bs.max_levels, 1) >= 3
                 OR (COALESCE(bs.max_levels, 0) = 0 AND bs.residential_building_sqft >= 2000)
             ) THEN 'mf5p'
        WHEN (ap.landuse_prefix LIKE 'A2' OR ap.landuse_prefix IN ('AT'))
             AND bs.residential_building_sqft > 0 THEN 'mf2to4'
        -- A2/AT with high intersection density but no building data → mf5p
        WHEN (ap.landuse_prefix LIKE 'A2' OR ap.landuse_prefix IN ('AT'))
             AND bs.residential_building_sqft = 0
             AND COALESCE(ap.lot_size_acres, 0) < 1.0
             AND COALESCE(id.intersection_density, 0) >= 100 THEN 'mf5p'
        -- A2 catch-all: building footprints exist but Overture didn't tag as residential.
        -- Landuse code already says multi-family, so default to conservative mf2to4.
        -- Without this, A2 + non-residential-only footprints falls through to
        -- 'WHEN other_building_sqft > 0 THEN civic', violating A2 audit.
        WHEN (ap.landuse_prefix LIKE 'A2' OR ap.landuse_prefix IN ('AT')) THEN 'mf2to4'
        -- Non-A2 parcels: classify by building footprint characteristics.
        -- Multi-family first (≥3 levels), then attached SF (600-2500 sqft,
        -- small lot), then SFR by lot size, then non-residential.
        WHEN bs.residential_building_sqft > 0
             AND COALESCE(bs.max_levels, 1) >= 3 THEN 'mf5p'
        -- Non-A2 residential parcels with large bldg on small lot → mf5p
        WHEN bs.residential_building_sqft > 0
             AND bs.residential_building_sqft >= 6000
             AND COALESCE(ap.lot_size_acres, 0) < 0.5 THEN 'mf5p'
        -- Attached SF: residential sqft in 600-2500 range, small lot, low height.
        -- Placed before SFR rules because sqft narrows the match; SFR rules
        -- catch any sqft on residential parcels that don't match attsf heuristics.
        WHEN bs.residential_building_sqft > 0
             AND bs.residential_building_sqft BETWEEN 600 AND 2500
             AND COALESCE(bs.max_levels, 1) BETWEEN 1 AND 3
             AND COALESCE(ap.lot_size_acres, 0) < 0.3
             AND COALESCE(ap.lot_size_acres, 0) > 0.0 THEN 'attsf'
        WHEN bs.residential_building_sqft > 0
             AND COALESCE(bs.max_levels, 1) < 3
             AND COALESCE(ap.lot_size_acres, 0) < 0.15 THEN 'detsf_sl'
        WHEN bs.residential_building_sqft > 0
             AND COALESCE(bs.max_levels, 1) < 3
             AND COALESCE(ap.lot_size_acres, 0) >= 0.15 THEN 'detsf_ll'
        WHEN bs.commercial_building_sqft > 0 THEN 'commercial'
        WHEN bs.industrial_building_sqft > 0 THEN 'industrial'
        WHEN bs.other_building_sqft > 0 THEN 'civic'
        ELSE NULL
    END AS built_form_key
FROM assessor_parcels ap
JOIN building_metrics bs ON ap.apn = bs.apn
LEFT JOIN int_density id ON ap.apn = id.apn
WHERE bs.total_footprint_sqft > 0
  AND CASE
        WHEN (ap.landuse_prefix LIKE 'A2' OR ap.landuse_prefix IN ('AT'))
             AND bs.residential_building_sqft > 0
             AND (
                 COALESCE(bs.max_levels, 1) >= 3
                 OR (COALESCE(bs.max_levels, 0) = 0 AND bs.residential_building_sqft >= 2000)
             ) THEN 'mf5p'
        WHEN (ap.landuse_prefix LIKE 'A2' OR ap.landuse_prefix IN ('AT'))
             AND bs.residential_building_sqft > 0 THEN 'mf2to4'
        -- A2/AT with high intersection density but no building data → mf5p
        WHEN (ap.landuse_prefix LIKE 'A2' OR ap.landuse_prefix IN ('AT'))
             AND bs.residential_building_sqft = 0
             AND COALESCE(ap.lot_size_acres, 0) < 1.0
             AND COALESCE(id.intersection_density, 0) >= 100 THEN 'mf5p'
        WHEN (ap.landuse_prefix LIKE 'A2' OR ap.landuse_prefix IN ('AT')) THEN 'mf2to4'
        WHEN bs.residential_building_sqft > 0
             AND COALESCE(bs.max_levels, 1) >= 3 THEN 'mf5p'
        -- Non-A2 residential parcels with large bldg on small lot → mf5p
        WHEN bs.residential_building_sqft > 0
             AND bs.residential_building_sqft >= 6000
             AND COALESCE(ap.lot_size_acres, 0) < 0.5 THEN 'mf5p'
        -- Attached SF tier2: res sqft 600-2500, small lot, low height
        WHEN bs.residential_building_sqft > 0
             AND bs.residential_building_sqft BETWEEN 600 AND 2500
             AND COALESCE(bs.max_levels, 1) BETWEEN 1 AND 3
             AND COALESCE(ap.lot_size_acres, 0) < 0.3
             AND COALESCE(ap.lot_size_acres, 0) > 0.0 THEN 'attsf'
        WHEN bs.residential_building_sqft > 0
             AND COALESCE(bs.max_levels, 1) < 3
             AND COALESCE(ap.lot_size_acres, 0) < 0.15 THEN 'detsf_sl'
        WHEN bs.residential_building_sqft > 0
             AND COALESCE(bs.max_levels, 1) < 3
             AND COALESCE(ap.lot_size_acres, 0) >= 0.15 THEN 'detsf_ll'
        WHEN bs.commercial_building_sqft > 0 THEN 'commercial'
        WHEN bs.industrial_building_sqft > 0 THEN 'industrial'
        WHEN bs.other_building_sqft > 0 THEN 'civic'
        ELSE NULL
    END IS NOT NULL;

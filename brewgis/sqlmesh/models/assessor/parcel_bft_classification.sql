MODEL (
  name brewgis.assessor.parcel_bft_classification,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    not_null(columns := (built_form_key_source)),
    unique_values(columns := (apn,)),
    assert_parcel_bft_classification_row_count,
    assert_bft_landuse_A1_to_detsf,
    assert_bft_landuse_A2_falls_through,
    assert_bft_landuse_A3_to_attsf,
    assert_bft_landuse_A4_to_detsf,
    assert_bft_landuse_AE_to_commercial,
    assert_bft_landuse_AF_to_industrial,
    assert_bft_landuse_AG_to_agricultural,
    assert_bft_landuse_AHAJ_to_civic,
    assert_bft_landuse_AD_to_undeveloped,
    assert_bft_landuse_AT_to_mf,
    assert_bft_landuse_commercial_codes_to_commercial,
    assert_bft_landuse_civic_codes_to_civic,
    assert_bft_landuse_industrial_codes_to_industrial,
    assert_bft_landuse_AQ_to_undeveloped,
    assert_bft_sales_sfr_lot_boundary,
    assert_bft_sales_mf_unit_boundary,
    assert_bft_tier_priority,
    assert_bft_tier3b_footprint_filter,
    assert_bft_tier4_area_heuristic
  )
);

-- Parcel Built Form Classification — 6-tier built_form_key derivation.
--
-- Split from parcel_dasymetric_weights to allow independent incremental
-- rebuilds. Expensive classification (63M query cost, KNN spatial joins)
-- lives here; weight computation (7M cost) lives in parcel_dasymetric_weights.
--
-- The built_form_key_source column tracks which tier provided the final
-- classification, enabling correct audit scoping.

WITH assessor_parcels AS (
    SELECT
        apn,
        geometry,
        COALESCE(NULLIF(lot_size_acres, 0), 0.01) AS lot_size_acres,
        landuse,
        LEFT(landuse::text, 2) AS landuse_prefix,
        LEFT(landuse::text, 1) AS landuse_first_char,
        zone,
        land_development_category
    FROM brewgis.assessor.sacog_assessor_parcels
),

-- Deduplicated sales data
sales_data AS (
    SELECT
        apn,
        actual_living_sqft,
        actual_building_sqft,
        property_type,
        sales_lot_size_acres,
        units
    FROM brewgis.assessor.sacog_assessor_sales_deduped
    WHERE apn IN (SELECT apn FROM assessor_parcels)
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
),

int_density AS (
    SELECT
        apn,
        intersection_density
    FROM brewgis.assessor.overture_intersection_density
),

-- Tier 1 (highest priority): from sales/property data
tier1_built_form_key AS (
    SELECT
        apn,
        CASE
            WHEN (property_type IN ('SFR', 'Single Family Residence') OR property_type LIKE 'Single Family%')
                AND COALESCE(sales_lot_size_acres, 0) < 0.15 THEN 'detsf_sl'
            WHEN (property_type IN ('SFR', 'Single Family Residence') OR property_type LIKE 'Single Family%')
                AND COALESCE(sales_lot_size_acres, 0) >= 0.15 THEN 'detsf_ll'
            WHEN property_type IN ('Condo', 'Condominium') THEN 'attsf'
            WHEN (property_type IN ('MF', 'Multiple Family Residence') OR property_type LIKE 'Multiple Family%')
                AND COALESCE(units, 0) BETWEEN 2 AND 4 THEN 'mf2to4'
            WHEN (property_type IN ('MF', 'Multiple Family Residence') OR property_type LIKE 'Multiple Family%')
                AND COALESCE(units, 0) >= 5 THEN 'mf5p'
            WHEN (property_type IN ('Commercial', 'Retail', 'Office', 'Restaurant', 'Hotel', 'Medical',
                  'Retail/Commercial', 'Commercial/Office')) THEN 'commercial'
            WHEN (property_type IN ('Industrial', 'Manufacturing', 'Warehouse', 'Industrial/Manufacturing',
                  'Transport/Warehouse', 'Construction')) THEN 'industrial'
            WHEN (property_type IN ('Agricultural', 'Farm/Ranch', 'Vacant Agricultural')) THEN 'agricultural'
            WHEN (property_type IN ('Civic', 'Institutional', 'Church', 'School', 'Government', 'Education',
                  'Public', 'Hospital', 'Medical Facility'))
                OR property_type LIKE '%Church%' OR property_type LIKE '%School%'
                OR property_type LIKE '%Government%' THEN 'civic'
            ELSE NULL
        END AS built_form_key,
        property_type,
        units,
        sales_lot_size_acres
    FROM sales_data
),

-- Tier 0: from landuse code (no anti-joins — priority via COALESCE)
tier0_built_form_key AS (
    SELECT
        ap.apn,
        CASE
            WHEN ap.landuse_prefix LIKE 'A1' THEN
                CASE
                    WHEN ap.lot_size_acres < 0.15 THEN 'detsf_sl'
                    ELSE 'detsf_ll'
                END
            -- A2% (multi-family): no tier0 classification. Falls through to tier2
            -- (Overture footprints, which distinguish mf2to4 vs mf5p from building
            -- square footage and height), then to tier3 landuse-constrained KNN.
            WHEN ap.landuse_prefix LIKE 'A2' THEN NULL
            WHEN ap.landuse_prefix LIKE 'A3' THEN 'attsf'
            WHEN ap.landuse_prefix LIKE 'A4' THEN 'detsf_sl'
            WHEN ap.landuse_prefix LIKE 'AE' THEN 'commercial'
            WHEN ap.landuse_prefix LIKE 'AF' THEN 'industrial'
            WHEN ap.landuse_prefix LIKE 'AG' THEN 'agricultural'
            WHEN ap.landuse_prefix IN ('AH', 'AJ') THEN 'civic'
            WHEN ap.landuse_prefix IN ('AT') THEN NULL
            WHEN ap.landuse_prefix IN ('CA', 'BA', 'BF', 'BC', 'BB', 'BE', 'BD', 'CG') THEN 'commercial'
            WHEN ap.landuse_prefix IN ('GC', 'GA', 'HJ') THEN 'civic'
            WHEN ap.landuse_prefix IN ('MS', 'MU', 'MP') THEN 'commercial'
            WHEN ap.landuse_prefix IN ('IA', 'IG', 'IB') THEN 'industrial'
            WHEN ap.landuse_prefix IN ('AQ') THEN 'undeveloped'
            WHEN ap.landuse_prefix LIKE 'AD' THEN 'undeveloped'
            ELSE NULL
        END AS built_form_key
    FROM assessor_parcels ap
    WHERE ap.landuse IS NOT NULL
),

-- Tier 2: from building footprints (no anti-joins — priority via COALESCE)
tier2_built_form_key AS (
    SELECT DISTINCT ON (ap.apn)
        ap.apn,
        CASE
            -- A2 parcels (multi-family) with building footprints → mf2to4 or mf5p
            WHEN (ap.landuse_prefix LIKE 'A2' OR ap.landuse_prefix IN ('AT'))
                 AND bs.residential_building_sqft > 0
                 AND COALESCE(bs.max_levels, 1) >= 3 THEN 'mf5p'
            WHEN (ap.landuse_prefix LIKE 'A2' OR ap.landuse_prefix IN ('AT'))
                 AND bs.residential_building_sqft > 0 THEN 'mf2to4'
            -- A2 catch-all: building footprints exist but Overture didn't tag as residential.
            -- Landuse code already says multi-family, so default to conservative mf2to4.
            -- Without this, A2 + non-residential-only footprints falls through to
            -- 'WHEN other_building_sqft > 0 THEN civic', violating A2 audit.
            WHEN (ap.landuse_prefix LIKE 'A2' OR ap.landuse_prefix IN ('AT')) THEN 'mf2to4'
            -- Original tier2 logic for non-A2 parcels
            WHEN bs.residential_building_sqft > 0
                 AND COALESCE(bs.max_levels, 1) < 3 THEN 'detsf_sl'
            WHEN bs.residential_building_sqft > 0
                 AND COALESCE(bs.max_levels, 1) >= 3 THEN 'mf5p'
            WHEN bs.commercial_building_sqft > 0 THEN 'commercial'
            WHEN bs.industrial_building_sqft > 0 THEN 'industrial'
            WHEN bs.other_building_sqft > 0 THEN 'civic'
            ELSE NULL
        END AS built_form_key
    FROM assessor_parcels ap
    JOIN building_metrics bs ON ap.apn = bs.apn
    WHERE bs.total_footprint_sqft > 0
),

-- Unknown parcels: no built_form_key from tier1 or tier0 (may have tier2)
unknown_parcels AS (
    SELECT
        ap.apn,
        ap.geometry,
        ap.lot_size_acres,
        COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
        ap.zone,
        COALESCE(id.intersection_density, 0) AS intersection_density,
        t2.built_form_key AS t2_bft,
        ap.land_development_category,
        ap.landuse_prefix
    FROM assessor_parcels ap
    LEFT JOIN building_metrics bs ON ap.apn = bs.apn
    LEFT JOIN int_density id ON ap.apn = id.apn
    LEFT JOIN tier2_built_form_key t2 ON ap.apn = t2.apn
    WHERE NOT EXISTS (SELECT 1 FROM tier1_built_form_key t1 WHERE t1.apn = ap.apn AND t1.built_form_key IS NOT NULL)
      AND NOT EXISTS (SELECT 1 FROM tier0_built_form_key t0 WHERE t0.apn = ap.apn AND t0.built_form_key IS NOT NULL)
),

tier3_candidates AS (
    SELECT
        u.apn,
        kf.neighbor_apn,
        kf.built_form_key,
        POWER(COALESCE((u.intersection_density - kf.intersection_density) / NULLIF(ps.s_int_dens, 0), 0), 2)
            + POWER(COALESCE((u.lot_size_acres - kf.lot_size_acres) / NULLIF(ps.s_ls, 0), 0), 2)
            + POWER(COALESCE((u.footprint_ratio - kf.footprint_ratio) / NULLIF(ps.s_fr, 0), 0), 2)
            AS distance_sq
    FROM unknown_parcels u
    LEFT JOIN brewgis.assessor.parcel_partition_stats ps
        ON COALESCE(u.land_development_category, '') = ps.land_development_category
    CROSS JOIN LATERAL (
        SELECT kf.apn AS neighbor_apn, kf.built_form_key,
               kf.intersection_density, kf.lot_size_acres, kf.footprint_ratio
        FROM brewgis.assessor.parcel_known_features kf
        WHERE kf.land_development_category = u.land_development_category
          AND kf.lot_size_acres BETWEEN
              u.lot_size_acres - 3 * COALESCE(ps.s_ls, u.lot_size_acres + 100)
              AND u.lot_size_acres + 3 * COALESCE(ps.s_ls, u.lot_size_acres + 100)
          AND ST_DWithin(u.geometry, kf.geometry, 5000)
          AND (
              (u.landuse_prefix LIKE 'A2' AND kf.built_form_key IN ('mf2to4', 'mf5p'))
              OR (u.landuse_prefix IN ('AT') AND kf.built_form_key IN ('mf2to4', 'mf5p'))
              OR (u.landuse_prefix NOT LIKE 'A2' AND u.landuse_prefix NOT IN ('AT'))
          )
        ORDER BY u.geometry <-> kf.geometry
        LIMIT 200
    ) kf
    WHERE u.t2_bft IS NULL
),

tier3_ranked AS (
    SELECT
        u.apn,
        u.neighbor_apn,
        u.built_form_key,
        u.distance_sq,
        ROW_NUMBER() OVER (
            PARTITION BY u.apn ORDER BY u.distance_sq
        ) AS rn
    FROM tier3_candidates u
),

tier3_built_form_key AS (
    SELECT
        apn,
        MODE() WITHIN GROUP (ORDER BY built_form_key) AS built_form_key
    FROM tier3_ranked
    WHERE rn <= 5
      AND distance_sq IS NOT NULL
    GROUP BY apn
),

tier3b_built_form_key AS (
    SELECT
        u.apn,
        'agricultural'::text AS built_form_key
    FROM unknown_parcels u
    WHERE u.lot_size_acres > 3.0
      AND COALESCE(u.footprint_ratio, 0) < 0.02
      AND u.t2_bft IS NULL
      AND ((u.landuse_prefix NOT LIKE 'A2' AND u.landuse_prefix NOT IN ('AT')) OR u.landuse_prefix IS NULL)
      AND NOT EXISTS (SELECT 1 FROM tier3_built_form_key t3 WHERE t3.apn = u.apn)
),

tier4_built_form_key AS (
    SELECT
        u.apn,
        CASE
            WHEN (u.landuse_prefix LIKE 'A2' OR u.landuse_prefix IN ('AT')) THEN 'mf2to4'
            WHEN u.lot_size_acres > 10.0 THEN 'agricultural'
            WHEN u.lot_size_acres > 3.0 THEN
                CASE
                    WHEN u.zone LIKE '%A%' THEN 'agricultural'
                    ELSE 'detsf_ll'
                END
            WHEN u.lot_size_acres > 0.4 THEN 'detsf_ll'
            WHEN u.lot_size_acres > 0.15 THEN 'detsf_sl'
            ELSE
                CASE (u.apn::bigint % 2)
                    WHEN 0 THEN 'mf2to4'
                    WHEN 1 THEN 'attsf'
                END
        END AS built_form_key
    FROM unknown_parcels u
    WHERE u.t2_bft IS NULL
      AND NOT EXISTS (SELECT 1 FROM tier3_built_form_key t3 WHERE t3.apn = u.apn)
      AND NOT EXISTS (SELECT 1 FROM tier3b_built_form_key t3b WHERE t3b.apn = u.apn)
),

-- Priority chain: tier1 → tier0 → tier2 → tier3 → tier3b → tier4
-- built_form_key_source tracks which tier provided the final classification
parcel_bft AS (
    SELECT
        ap.apn,
        COALESCE(t1.built_form_key, t0.built_form_key, t2.built_form_key,
                 t3.built_form_key, t3b.built_form_key, t4.built_form_key) AS built_form_key,
        CASE
            WHEN t1.built_form_key IS NOT NULL THEN 'tier1'
            WHEN t0.built_form_key IS NOT NULL THEN 'tier0'
            WHEN t2.built_form_key IS NOT NULL THEN 'tier2'
            WHEN t3.built_form_key IS NOT NULL THEN 'tier3'
            WHEN t3b.built_form_key IS NOT NULL THEN 'tier3b'
            WHEN t4.built_form_key IS NOT NULL THEN 'tier4'
            ELSE NULL
        END AS built_form_key_source
    FROM assessor_parcels ap
    LEFT JOIN tier1_built_form_key t1 ON ap.apn = t1.apn AND t1.built_form_key IS NOT NULL
    LEFT JOIN tier0_built_form_key t0 ON ap.apn = t0.apn AND t0.built_form_key IS NOT NULL
    LEFT JOIN tier2_built_form_key t2 ON ap.apn = t2.apn AND t2.built_form_key IS NOT NULL
    LEFT JOIN tier3_built_form_key t3 ON ap.apn = t3.apn
    LEFT JOIN tier3b_built_form_key t3b ON ap.apn = t3b.apn
    LEFT JOIN tier4_built_form_key t4 ON ap.apn = t4.apn
)

SELECT
    pb.apn,
    pb.built_form_key,
    pb.built_form_key_source,
    CASE WHEN pb.built_form_key IN ('detsf_sl','detsf_ll','attsf','mf2to4','mf5p')
         THEN pb.built_form_key ELSE NULL
    END AS du_subtype,
    CASE WHEN pb.built_form_key IN ('detsf_sl','detsf_ll','attsf','mf2to4','mf5p')
         THEN 1 ELSE 0
    END AS is_residential,
    ap.landuse,
    ap.lot_size_acres,
    ap.zone,
    COALESCE(ap.land_development_category, 'urban') AS land_development_category,
    COALESCE(sd.actual_living_sqft, 0)::double precision AS actual_living_sqft,
    COALESCE(sd.actual_building_sqft, 0)::double precision AS actual_building_sqft,
    sd.property_type,
    sd.sales_lot_size_acres,
    sd.units,
    COALESCE(bs.residential_building_sqft, 0)::double precision AS residential_building_sqft,
    COALESCE(bs.commercial_building_sqft, 0)::double precision AS commercial_building_sqft,
    COALESCE(bs.industrial_building_sqft, 0)::double precision AS industrial_building_sqft,
    COALESCE(bs.other_building_sqft, 0)::double precision AS other_building_sqft,
    COALESCE(bs.total_footprint_sqft, 0)::double precision AS total_footprint_sqft,
    COALESCE(bs.building_count, 0)::integer AS building_count,
    COALESCE(bs.footprint_ratio, 0)::double precision AS footprint_ratio,
    COALESCE(bs.max_levels, 0)::integer AS max_levels,
    COALESCE(id.intersection_density, 0)::double precision AS intersection_density
FROM assessor_parcels ap
LEFT JOIN parcel_bft pb ON ap.apn = pb.apn
LEFT JOIN sales_data sd ON ap.apn = sd.apn
LEFT JOIN building_metrics bs ON ap.apn = bs.apn
LEFT JOIN int_density id ON ap.apn = id.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_bft_classification_apn_@snapshot_hash
  ON @this_model USING btree (apn);
ANALYZE @this_model;

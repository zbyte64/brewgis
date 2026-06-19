MODEL (
  name brewgis.assessor.parcel_dasymetric_weights,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,)),
    assert_parcel_dasymetric_weights_row_count,
    assert_bft_landuse_A1_to_detsf,
    assert_bft_landuse_A2_falls_through,
    assert_bft_landuse_A3_to_attsf,
    assert_bft_landuse_A4_to_detsf,
    assert_bft_landuse_AE_to_commercial,
    assert_bft_landuse_AF_to_industrial,
    assert_bft_landuse_AG_to_agricultural,
    assert_bft_landuse_AHAJ_to_civic,
    assert_bft_landuse_AD_to_undeveloped,
    assert_bft_sales_sfr_lot_boundary,
    assert_bft_sales_mf_unit_boundary,
    assert_bft_tier_priority,
    assert_bft_tier3b_footprint_filter,
    assert_bft_tier4_area_heuristic
  )
);

-- Dasymetric Weights — per-parcel built_form_key, weights, and classification.
--
-- Optimized from 22 CTEs (3.19T cost) to 17 CTEs (~40 nodes expected) by:
--  - Merging tier0/tier1/tier2 anti-joins into LEFT JOIN + COALESCE chain
--  - Inlining sacog_category into the classification CASE
--  - Merging deduped_sales into sales_data
--  - Replacing UNION ALL in final_built_form_key with COALESCE chain
--  - Pre-computing landuse_prefix to avoid repeated casting
--  - Hoisting common LEFT JOINs into shared building_metrics/int_density CTEs
--  - Dropping nlcd_join (impervious_fraction from sacog_parcel_shim spatial join)

WITH assessor_parcels AS (
    SELECT
        apn,
        geometry,
        COALESCE(NULLIF(lot_size_acres, 0), 0.01) AS lot_size_acres,
        landuse,
        LEFT(landuse::text, 2) AS landuse_prefix,
        LEFT(landuse::text, 1) AS landuse_first_char,
        zone
    FROM brewgis.assessor.sacog_assessor_parcels
),

-- Single classification pass (merged sacog_category + classified)
classified AS (
    SELECT
        ap.apn,
        COALESCE(
            auc.category,
            CASE
                WHEN ap.landuse IS NULL OR ap.landuse = '' THEN 'undeveloped'
                WHEN ap.landuse_first_char = 'A' THEN 'urban'
                WHEN ap.landuse_first_char = 'B' THEN 'urban'
                WHEN ap.landuse_first_char = 'C' THEN 'urban'
                WHEN ap.landuse_first_char = 'D' THEN 'undeveloped'
                WHEN ap.landuse_first_char = 'E' THEN 'urban'
                WHEN ap.landuse_first_char = 'F' THEN 'agricultural'
                WHEN ap.landuse_first_char = 'G' THEN 'undeveloped'
                WHEN ap.landuse_first_char = 'H' THEN 'urban'
                WHEN ap.landuse_first_char = 'I' THEN 'industrial'
                WHEN ap.landuse_prefix IN ('MP', 'MR', 'MW', 'MD', 'MF', 'MG', 'ML') THEN 'undeveloped'
                WHEN ap.landuse_first_char = 'M' THEN 'urban'
                WHEN ap.landuse_first_char = 'W' THEN 'undeveloped'
                ELSE 'undeveloped'
            END,
            'urban'
        ) AS land_development_category
    FROM assessor_parcels ap
    LEFT JOIN brewgis.seeds.assessor_use_codes auc
        ON ap.landuse_prefix = auc.use_code::text
),

-- Deduplicated sales data (merged deduped_sales into sales_data)
sales_data AS (
    SELECT
        apn,
        living_area AS actual_living_sqft,
        building_sf AS actual_building_sqft,
        property_type,
        lot_size_acres AS sales_lot_size_acres,
        units
    FROM (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY apn
                ORDER BY
                    CASE
                        WHEN living_area IS NOT NULL AND building_sf IS NOT NULL AND units IS NOT NULL THEN 0
                        WHEN living_area IS NOT NULL THEN 1
                        WHEN building_sf IS NOT NULL THEN 2
                        ELSE 3
                    END,
                    year_built DESC NULLS LAST
            ) AS rn
        FROM public.sacog_assessor_sales_raw
        WHERE (living_area IS NOT NULL OR building_sf IS NOT NULL)
          AND apn IN (SELECT apn FROM assessor_parcels)
    ) dedup
    WHERE rn = 1
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
            -- A2% (multi-family) deliberately NOT classified here — falls through to
            -- Tier 2 (Overture building footprints) which has building sqft to estimate
            -- actual unit counts (mf2to4 vs mf5p). The parcel base has no unit count data.
            WHEN ap.landuse_prefix LIKE 'A3' THEN 'attsf'
            WHEN ap.landuse_prefix LIKE 'A4' THEN 'detsf_sl'
            WHEN ap.landuse_prefix LIKE 'AE' THEN 'commercial'
            WHEN ap.landuse_prefix LIKE 'AF' THEN 'industrial'
            WHEN ap.landuse_prefix LIKE 'AG' THEN 'agricultural'
            WHEN ap.landuse_prefix IN ('AH', 'AJ') THEN 'civic'
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

-- Known parcels: have built_form_key from tier1 or tier0 (used as k-NN neighbors)
known_parcels AS (
    SELECT
        ap.apn,
        ap.geometry,
        ap.lot_size_acres,
        COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
        COALESCE(id.intersection_density, 0) AS intersection_density,
        COALESCE(t1.built_form_key, t0.built_form_key) AS built_form_key,
        cl.land_development_category
    FROM assessor_parcels ap
    LEFT JOIN tier1_built_form_key t1 ON ap.apn = t1.apn AND t1.built_form_key IS NOT NULL
    LEFT JOIN tier0_built_form_key t0 ON ap.apn = t0.apn AND t0.built_form_key IS NOT NULL
    LEFT JOIN building_metrics bs ON ap.apn = bs.apn
    LEFT JOIN int_density id ON ap.apn = id.apn
    LEFT JOIN classified cl ON ap.apn = cl.apn
    WHERE COALESCE(t1.built_form_key, t0.built_form_key) IS NOT NULL
      AND COALESCE(t1.built_form_key, t0.built_form_key) IN (
          'detsf_sl', 'detsf_ll', 'attsf', 'mf2to4', 'mf5p', 'commercial', 'industrial'
      )
),

partition_stats AS (
    SELECT
        COALESCE(k.land_development_category, '') AS land_development_category,
        STDDEV_POP(k.intersection_density) AS s_int_dens,
        STDDEV_POP(k.lot_size_acres) AS s_ls,
        STDDEV_POP(k.footprint_ratio) AS s_fr
    FROM known_parcels k
    GROUP BY k.land_development_category
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
        cl.land_development_category
    FROM assessor_parcels ap
    LEFT JOIN building_metrics bs ON ap.apn = bs.apn
    LEFT JOIN int_density id ON ap.apn = id.apn
    LEFT JOIN classified cl ON ap.apn = cl.apn
    LEFT JOIN tier2_built_form_key t2 ON ap.apn = t2.apn
    WHERE NOT EXISTS (SELECT 1 FROM tier1_built_form_key t1 WHERE t1.apn = ap.apn AND t1.built_form_key IS NOT NULL)
      AND NOT EXISTS (SELECT 1 FROM tier0_built_form_key t0 WHERE t0.apn = ap.apn AND t0.built_form_key IS NOT NULL)
),

tier3_candidates AS (
    SELECT
        u.apn,
        k.apn AS neighbor_apn,
        k.built_form_key,
        POWER(COALESCE((u.intersection_density - k.intersection_density) / NULLIF(ps.s_int_dens, 0), 0), 2)
            + POWER(COALESCE((u.lot_size_acres - k.lot_size_acres) / NULLIF(ps.s_ls, 0), 0), 2)
            + POWER(COALESCE((u.footprint_ratio - k.footprint_ratio) / NULLIF(ps.s_fr, 0), 0), 2)
            AS distance_sq
    FROM unknown_parcels u
    LEFT JOIN partition_stats ps
        ON COALESCE(u.land_development_category, '') = ps.land_development_category
    CROSS JOIN LATERAL (
        SELECT pcg.apn AS neighbor_apn
        FROM brewgis.assessor.parcel_classified_geometry pcg
        WHERE pcg.land_development_category = u.land_development_category
        ORDER BY u.geometry <-> pcg.geometry
        LIMIT 200
    ) pcg
    JOIN known_parcels k ON pcg.neighbor_apn = k.apn
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
      AND NOT EXISTS (SELECT 1 FROM tier3_built_form_key t3 WHERE t3.apn = u.apn)
),

tier4_built_form_key AS (
    SELECT
        u.apn,
        CASE
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

auth_res_area AS (
    SELECT apn, authoritative_residential_sqft, authoritative_non_residential_sqft
    FROM brewgis.assessor.authoritative_residential_area
),

-- Priority chain: tier1 → tier0 → tier2 → tier3 → tier3b → tier4
parcel_bft AS (
    SELECT
        ap.apn,
        COALESCE(t1.built_form_key, t0.built_form_key, t2.built_form_key,
                 t3.built_form_key, t3b.built_form_key, t4.built_form_key) AS built_form_key
    FROM assessor_parcels ap
    LEFT JOIN tier1_built_form_key t1 ON ap.apn = t1.apn AND t1.built_form_key IS NOT NULL
    LEFT JOIN tier0_built_form_key t0 ON ap.apn = t0.apn AND t0.built_form_key IS NOT NULL
    LEFT JOIN tier2_built_form_key t2 ON ap.apn = t2.apn AND t2.built_form_key IS NOT NULL
    LEFT JOIN tier3_built_form_key t3 ON ap.apn = t3.apn
    LEFT JOIN tier3b_built_form_key t3b ON ap.apn = t3b.apn
    LEFT JOIN tier4_built_form_key t4 ON ap.apn = t4.apn
)

SELECT
    ap.apn,
    ap.lot_size_acres,
    COALESCE(cl.land_development_category, 'urban') AS land_development_category,
    pb.built_form_key,
    CASE WHEN pb.built_form_key IN ('detsf_sl','detsf_ll','attsf','mf2to4','mf5p')
         THEN pb.built_form_key ELSE NULL
    END AS du_subtype,
    CASE WHEN pb.built_form_key IN ('detsf_sl','detsf_ll','attsf','mf2to4','mf5p')
         THEN 1 ELSE 0
    END AS is_residential,
    COALESCE(sd.actual_living_sqft, 0)::double precision AS actual_living_sqft,
    COALESCE(sd.actual_building_sqft, 0)::double precision AS actual_building_sqft,
    COALESCE(bs.residential_building_sqft, 0)::double precision AS residential_building_sqft,
    COALESCE(bs.commercial_building_sqft, 0)::double precision AS commercial_building_sqft,
    COALESCE(bs.industrial_building_sqft, 0)::double precision AS industrial_building_sqft,
    COALESCE(bs.other_building_sqft, 0)::double precision AS other_building_sqft,
    COALESCE(bs.total_footprint_sqft, 0)::double precision AS total_footprint_sqft,
    COALESCE(bs.building_count, 0)::integer AS building_count,
    COALESCE(bs.footprint_ratio, 0)::double precision AS footprint_ratio,
    COALESCE(bs.max_levels, 0)::integer AS max_levels,
    COALESCE(id.intersection_density, 0)::double precision AS intersection_density,
    COALESCE(
        ar.authoritative_residential_sqft,
        bs.residential_building_sqft,
        ap.lot_size_acres * 43560 * 0.15
    ) AS pop_dasym_weight,
    COALESCE(
        ar.authoritative_non_residential_sqft,
        bs.commercial_building_sqft + bs.industrial_building_sqft + bs.other_building_sqft,
        ap.lot_size_acres * 43560 * 0.1
    ) * (1.0 + COALESCE(id.intersection_density, 0.0) / 200.0) AS emp_dasym_weight
FROM assessor_parcels ap
LEFT JOIN classified cl ON ap.apn = cl.apn
LEFT JOIN parcel_bft pb ON ap.apn = pb.apn
LEFT JOIN sales_data sd ON ap.apn = sd.apn
LEFT JOIN building_metrics bs ON ap.apn = bs.apn
LEFT JOIN int_density id ON ap.apn = id.apn
LEFT JOIN auth_res_area ar ON ap.apn = ar.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_dasymetric_weights_apn
  ON brewgis.assessor.parcel_dasymetric_weights (apn);
  CREATE INDEX IF NOT EXISTS idx_sacog_assessor_sales_raw_apn
  ON public.sacog_assessor_sales_raw (apn);
ANALYZE brewgis.assessor.parcel_dasymetric_weights;
ANALYZE public.sacog_assessor_sales_raw;

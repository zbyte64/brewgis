MODEL (
  name brewgis.assessor.parcel_du_estimation,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn))
  )
);

-- Dwelling Unit Estimation — 6-tier cascade per Section 5 of methodology.
--
-- Computes per-parcel dwelling units, vacancy rate, and population weight
-- using built_form_key, Overture building sqft, and assessor unit counts.
--
-- Also computes region_avg_overture_sqft_per_unit calibration from parcels
-- with both assessor unit counts and Overture residential building sqft,
-- using k-NN in intersection density space (k=20, same subtype).
--
-- Output:
--   du                     — final dwelling unit estimate (6-tier cascade)
--   vacancy_rate           — from built_form_key defaults
--   household_size         — from ACS block group (area-weighted mean)
--   pop_dasym_weight       — du × household_size
--   hh_dasym_weight        — du × (1 - vacancy_rate)

WITH parcel_input AS (
    SELECT
        apn,
        built_form_key,
        du_subtype,
        is_residential,
        lot_size_acres,
        land_development_category,
        residential_building_sqft,
        intersection_density,
        actual_living_sqft,
        actual_building_sqft
    FROM brewgis.assessor.parcel_dasymetric_weights
),

-- ── Assessor units (Tier 1 source) ─────────────────────────────────────────
assessor_units AS (
    SELECT DISTINCT ON (apn)
        apn,
        COALESCE(NULLIF(units, 0), 0) AS units,
        property_type
    FROM public.sacog_assessor_sales_raw
    ORDER BY apn, year_built DESC NULLS LAST
),

-- ── ACS household size (from staging.acs_block_group, area-weighted) ───────
-- Joins APN geometry directly to ACS block groups to avoid circular dependency
-- through sacog_comparison_dasymetric.
acs_hh_size AS (
    SELECT
        p.apn,
        SUM(p.hh / NULLIF(p.du, 0) * p.intersect_area) / NULLIF(SUM(p.intersect_area), 0) AS hh_size
    FROM (
        SELECT
            sap.apn,
            a.hh,
            a.du,
            ST_Area(ST_Intersection(
                ST_Transform(sap.geometry, @VAR('local_srid', 3310)),
                ST_Transform(a.geometry, @VAR('local_srid', 3310))
            )) AS intersect_area
        FROM brewgis.assessor.sacog_assessor_parcels sap
        JOIN brewgis.staging.acs_block_group a
            ON ST_Intersects(sap.geometry, a.geometry)
        WHERE a.du > 0
    ) p
    GROUP BY p.apn
),

-- ── Merge ACS hh_size with APN-level data ─────────────────────────────────
parcel_hh_size AS (
    SELECT
        p.apn,
        p.built_form_key,
        p.du_subtype,
        p.is_residential,
        p.lot_size_acres,
        p.land_development_category,
        p.residential_building_sqft,
        p.intersection_density,
        p.actual_living_sqft,
        p.actual_building_sqft,
        au.units AS assessor_units,
        au.property_type,
        COALESCE(acs.hh_size, 2.5) AS hh_size
    FROM parcel_input p
    LEFT JOIN assessor_units au ON p.apn = au.apn
    LEFT JOIN acs_hh_size acs ON p.apn = acs.apn
),

-- ── Calibration parcels (have both assessor.units > 0 and Overture res sqft > 0) ──
calibration_parcels AS (
    SELECT
        apn,
        residential_building_sqft,
        assessor_units,
        intersection_density,
        CASE
            WHEN assessor_units BETWEEN 2 AND 4 THEN 'mf2to4'
            WHEN assessor_units >= 5 THEN 'mf5p'
        END AS du_subtype
    FROM parcel_hh_size
    WHERE residential_building_sqft > 0
      AND assessor_units > 0
      AND assessor_units >= 2
),

-- ── region_avg_overture_sqft_per_unit via k-NN in int_dens space (k=20) ─────
-- For each MF parcel, find 20 nearest calibration parcels in intersection
-- density space and compute the ratio of sums for the subtype.
-- Fallback to county-wide subtype avg when no calibration parcels within
-- a reasonable int_dens distance.
knn_calibration AS (
    SELECT
        p.apn,
        c.du_subtype,
        SUM(c.residential_building_sqft) / NULLIF(SUM(c.assessor_units), 0) AS region_avg_sqft_per_unit,
        COUNT(*) AS calib_count
    FROM parcel_hh_size p
    CROSS JOIN LATERAL (
        SELECT c.residential_building_sqft, c.assessor_units, c.du_subtype
        FROM calibration_parcels c
        WHERE c.du_subtype = (
            CASE
                WHEN p.du_subtype IN ('mf2to4', 'mf5p') THEN p.du_subtype
                ELSE NULL
            END
        )
        ORDER BY ABS(p.intersection_density - c.intersection_density)
        LIMIT 20
    ) c
    WHERE p.du_subtype IN ('mf2to4', 'mf5p')
    GROUP BY p.apn, c.du_subtype
),

-- ── County-wide subtype avg (fallback for k-NN) ───────────────────────────
county_subtype_avg AS (
    SELECT
        du_subtype,
        SUM(residential_building_sqft) / NULLIF(SUM(assessor_units), 0) AS region_avg_sqft_per_unit
    FROM calibration_parcels
    GROUP BY du_subtype
),

-- ── Final calibration: k-NN if available, else county avg ──────────────────
calibration AS (
    SELECT
        p.apn,
        COALESCE(
            CASE
                WHEN k.calib_count >= 5 THEN k.region_avg_sqft_per_unit
                ELSE csa.region_avg_sqft_per_unit
            END,
            csa.region_avg_sqft_per_unit,
            1259.0  -- global default for mf2to4 (from SACOG data)
        ) AS region_avg_sqft_per_unit,
        CASE
            WHEN p.du_subtype = 'mf2to4' THEN 2
            WHEN p.du_subtype = 'mf5p' THEN 5
            ELSE NULL
        END AS min_du
    FROM parcel_hh_size p
    LEFT JOIN knn_calibration k ON p.apn = k.apn
    LEFT JOIN county_subtype_avg csa
        ON (p.du_subtype = csa.du_subtype)
    WHERE p.du_subtype IN ('mf2to4', 'mf5p')
),

-- ── Vacancy rate from built_form_key (Section 5) ───────────────────────────
vacancy_cascade AS (
    SELECT
        apn,
        CASE
            WHEN built_form_key IN ('detsf_sl', 'detsf_ll') THEN 0.025
            WHEN built_form_key IN ('attsf', 'mf2to4') THEN 0.050
            WHEN built_form_key = 'mf5p' THEN 0.080
            WHEN land_development_category IN ('urban', 'mixed_use') THEN 0.050
            ELSE 0.050
        END AS vacancy_rate
    FROM parcel_hh_size
),

-- ── 6-tier DU estimation cascade (Section 5) ───────────────────────────────
du_estimation AS (
    SELECT
        p.apn,
        p.built_form_key,
        p.du_subtype,
        p.is_residential,
        p.hh_size,
        v.vacancy_rate,
        -- Tier 1: Direct assessor observation
        CASE
            WHEN p.assessor_units IS NOT NULL AND p.assessor_units > 0
            THEN p.assessor_units::double precision
            ELSE NULL
        END AS du_tier1,
        -- Tier 2: SFR subtypes → du = 1
        CASE
            WHEN p.built_form_key IN ('detsf_sl', 'detsf_ll', 'attsf')
            THEN 1.0
            ELSE NULL
        END AS du_tier2,
        -- Tier 3: MF subtype + building sqft
        CASE
            WHEN p.built_form_key IN ('mf2to4', 'mf5p')
                 AND COALESCE(p.residential_building_sqft, 0) > 0
            THEN GREATEST(
                c.min_du::double precision,
                ROUND(p.residential_building_sqft / NULLIF(c.region_avg_sqft_per_unit, 0))::double precision
            )
            ELSE NULL
        END AS du_tier3,
        -- Tier 4: MF subtype, no building data
        CASE
            WHEN p.built_form_key IN ('mf2to4', 'mf5p')
                 AND COALESCE(p.residential_building_sqft, 0) = 0
            THEN c.min_du::double precision
            ELSE NULL
        END AS du_tier4,
        -- Tier 5: urban/mixed_use default
        CASE
            WHEN p.land_development_category IN ('urban', 'mixed_use')
                 AND (p.assessor_units IS NULL OR p.assessor_units <= 0)
                 AND p.built_form_key NOT IN ('detsf_sl', 'detsf_ll', 'attsf', 'mf2to4', 'mf5p')
            THEN 1.0
            ELSE NULL
        END AS du_tier5,
        -- Tier 6: non-residential → du = 0
        CASE
            WHEN p.built_form_key IN ('commercial', 'industrial', 'civic', 'agricultural')
                 OR p.land_development_category IN ('industrial', 'agricultural', 'undeveloped')
            THEN 0.0
            ELSE NULL
        END AS du_tier6
    FROM parcel_hh_size p
    LEFT JOIN calibration c ON p.apn = c.apn
    LEFT JOIN vacancy_cascade v ON p.apn = v.apn
),

-- ── Collapse cascade into single du value ──────────────────────────────────
du_final AS (
    SELECT
        apn,
        COALESCE(
            du_tier1,
            du_tier2,
            du_tier3,
            du_tier4,
            du_tier5,
            du_tier6,
            -- Default: if nothing matched, assume 0 for non-res or 1 for urban
            0.0
        ) AS du,
        built_form_key,
        du_subtype,
        is_residential,
        hh_size,
        vacancy_rate
    FROM du_estimation
)

SELECT
    apn,
    du::double precision AS du,
    du_subtype,
    built_form_key,
    is_residential,
    hh_size::double precision AS hh_size,
    vacancy_rate::double precision AS vacancy_rate,
    -- Population weight: du × household_size (Section 5)
    (du * COALESCE(NULLIF(hh_size, 0), 2.5))::double precision AS pop_dasym_weight,
    -- Household weight: du × (1 - vacancy_rate) (Section 5)
    (du * (1.0 - COALESCE(vacancy_rate, 0.05)))::double precision AS hh_dasym_weight,
    -- Households: du × (1 - vacancy_rate)
    (du * (1.0 - COALESCE(vacancy_rate, 0.05)))::double precision AS hh
FROM du_final;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_parcel_du_estimation_apn
  ON brewgis.assessor.parcel_du_estimation (apn)
);
ANALYZE brewgis.assessor.parcel_du_estimation;

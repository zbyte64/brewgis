MODEL (
  name brewgis.assessor.parcel_du_estimation,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,)),
    assert_parcel_du_estimation_row_count(parcel_table := 'brewgis.assessor.parcel_dasymetric_weights'),
    assert_du_assessor_units_direct,
    assert_du_vacancy_rates
  )
);

-- Dwelling Unit Estimation — 2-tier cascade using LightGBM regressor.
--
-- Tier 1: Direct assessor unit observation (from sales raw).
-- Tier 2: LightGBM regressor prediction (du_total_regressor) from
--         parcel_dasymetric_weights.
-- Fallback: 0.0 (non-residential parcels).
--
-- DU subtype breakdown is provided directly by the regressor (du_detsf_sl,
-- du_detsf_ll, du_attsf, du_mf2to4, du_mf5p).
--
-- Vacancy rate: flat 0.05 default since built_form_key is no longer available.
--
-- Output:
--   du                     — final dwelling unit estimate (2-tier cascade)
--   vacancy_rate           — flat 0.05 default
--   household_size         — from ACS block group (area-weighted mean)
--   pop_dasym_weight       — du × household_size
--   hh_dasym_weight        — du × (1 - vacancy_rate)

WITH parcel_input AS (
    SELECT
        apn,
        du_detsf_sl_regressor,
        du_detsf_ll_regressor,
        du_attsf_regressor,
        du_mf2to4_regressor,
        du_mf5p_regressor,
        du_total_regressor,
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

-- ── ACS household size (from assessor.parcel_acs_intersections, area-weighted) ─
acs_hh_size AS (
    SELECT
        p.apn,
        SUM(p.hh / NULLIF(p.du, 0) * p.intersect_area_sqft) / NULLIF(SUM(p.intersect_area_sqft), 0) AS hh_size
    FROM brewgis.assessor.parcel_acs_intersections p
    GROUP BY p.apn
),

-- ── Merge ACS hh_size and regressor output with APN-level data ─────────────
parcel_data AS (
    SELECT
        p.apn,
        p.du_detsf_sl_regressor,
        p.du_detsf_ll_regressor,
        p.du_attsf_regressor,
        p.du_mf2to4_regressor,
        p.du_mf5p_regressor,
        p.du_total_regressor,
        p.land_development_category,
        p.lot_size_acres,
        p.residential_building_sqft,
        COALESCE(au.units, 0) AS assessor_units,
        COALESCE(acs.hh_size, 2.5) AS hh_size
    FROM parcel_input p
    LEFT JOIN assessor_units au ON p.apn = au.apn
    LEFT JOIN acs_hh_size acs ON p.apn = acs.apn
),

-- ── 2-tier DU estimation cascade (replaces 6-tier BFT-based cascade) ────────
-- Tier 1: Direct assessor observation (units from sales raw)
-- Tier 2: LightGBM regressor prediction (du_total_regressor)
-- Fallback: 0.0 for parcels without assessor units or regressor prediction
du_estimation AS (
    SELECT
        apn,
        -- 2-tier cascade: assessor_units > regressor > 0
        COALESCE(
            NULLIF(assessor_units::double precision, 0),
            du_total_regressor,
            0.0
        ) AS du,
        du_detsf_sl_regressor,
        du_detsf_ll_regressor,
        du_attsf_regressor,
        du_mf2to4_regressor,
        du_mf5p_regressor,
        du_total_regressor,
        hh_size,
        0.05::double precision AS vacancy_rate,
        assessor_units,
        residential_building_sqft,
        land_development_category
    FROM parcel_data
)

SELECT
    apn,
    du::double precision AS du,
    du_detsf_sl_regressor::double precision AS du_detsf_sl_regressor,
    du_detsf_ll_regressor::double precision AS du_detsf_ll_regressor,
    du_attsf_regressor::double precision AS du_attsf_regressor,
    du_mf2to4_regressor::double precision AS du_mf2to4_regressor,
    du_mf5p_regressor::double precision AS du_mf5p_regressor,
    du_total_regressor::double precision AS du_total_regressor,
    hh_size::double precision AS hh_size,
    vacancy_rate::double precision AS vacancy_rate,
    assessor_units::integer AS assessor_units,
    residential_building_sqft::double precision AS residential_building_sqft,
    land_development_category,
    -- Population weight: du × household_size
    (du * COALESCE(NULLIF(hh_size, 0), 2.5))::double precision AS pop_dasym_weight,
    -- Household weight: du × (1 - vacancy_rate)
    (du * (1.0 - COALESCE(vacancy_rate, 0.05)))::double precision AS hh_dasym_weight,
    -- Households: du × (1 - vacancy_rate)
    (du * (1.0 - COALESCE(vacancy_rate, 0.05)))::double precision AS hh
FROM du_estimation;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_du_estimation_apn_@snapshot_hash
  ON @this_model USING btree (apn);
ANALYZE @this_model;

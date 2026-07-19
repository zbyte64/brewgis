MODEL (
  name brewgis.fresno.du_estimation,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,)),
    assert_parcel_du_estimation_row_count(parcel_table := 'brewgis.fresno.dasymetric_weights'),
    assert_du_vacancy_rates
  )
);

-- Dwelling Unit Estimation — 2-tier cascade using LightGBM regressor.
--
-- Tier 1: Direct assessor unit observation → always NULL for Fresno (no assessor data)
-- Tier 2: LightGBM regressor prediction (du_total_regressor)
-- Fallback: 0.0 (non-residential parcels).
--
-- Since Fresno has no assessor units, Tier 1 always falls through to Tier 2.
-- The du_total_regressor comes from the fresno_du_regressor Python FULL model,
-- which is populated during the same SQLMesh plan execution.
--
-- Vacancy rate: flat 0.05 default.
-- Household size: from ACS block group (area-weighted, geography-agnostic join).

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
        actual_living_sqft,
        actual_building_sqft
    FROM brewgis.fresno.dasymetric_weights
),

-- ACS household size (area-weighted, joins on block group geometry — geography-agnostic)
acs_hh_size AS (
    SELECT
        p.parcel_id AS apn,
        SUM(
            p.hh / NULLIF(p.du, 0) * ST_Area(ST_Intersection(p.local_geometry, a.local_envelope))
        ) / NULLIF(SUM(ST_Area(ST_Intersection(p.local_geometry, a.local_envelope))), 0) AS hh_size
    FROM brewgis.fresno.parcel_shim p
    JOIN brewgis.assessor.acs_block_group_projected a
        ON ST_Intersects(p.local_geometry, a.geometry)
    GROUP BY p.parcel_id
),

-- ── Merge ACS hh_size — Fresno has no assessor units ──────────────────────
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
        COALESCE(acs.hh_size, 2.5) AS hh_size
    FROM parcel_input p
    LEFT JOIN acs_hh_size acs ON p.apn = acs.apn
),

-- ── 2-tier DU estimation cascade ──────────────────────────────────────────
-- Tier 1: Direct assessor observation → always NULL for Fresno
-- Tier 2: LightGBM regressor prediction (du_total_regressor)
-- Fallback: 0.0
du_estimation AS (
    SELECT
        apn,
        COALESCE(
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
    NULL::integer AS assessor_units,
    0::double precision AS residential_building_sqft,
    land_development_category,
    -- Population weight: du × household_size
    (du * COALESCE(NULLIF(hh_size, 0), 2.5))::double precision AS pop_dasym_weight,
    -- Household weight: du × (1 - vacancy_rate)
    (du * (1.0 - COALESCE(vacancy_rate, 0.05)))::double precision AS hh_dasym_weight,
    -- Households: du × (1 - vacancy_rate)
    (du * (1.0 - COALESCE(vacancy_rate, 0.05)))::double precision AS hh
FROM du_estimation;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_fresno_du_estimation_apn_@snapshot_hash
  ON @this_model USING btree (apn);
ANALYZE @this_model;

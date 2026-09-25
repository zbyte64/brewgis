MODEL (
  name brewgis.@{region}.parcel_du_estimation,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  description 'APN-level dwelling unit estimate from a 2-tier cascade: assessor units, then the LightGBM regressor.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) of the parcel.',
    du = 'Final dwelling unit estimate from the 2-tier cascade (assessor units, then regressor).',
    du_detsf_sl_regressor = 'Regressor estimate of detached single-family small-lot dwelling units.',
    du_detsf_ll_regressor = 'Regressor estimate of detached single-family large-lot dwelling units.',
    du_attsf_regressor = 'Regressor estimate of attached single-family dwelling units.',
    du_mf2to4_regressor = 'Regressor estimate of multi-family 2-4 unit dwelling units.',
    du_mf5p_regressor = 'Regressor estimate of multi-family 5+ unit dwelling units.',
    du_total_regressor = 'Regressor estimate of total dwelling units across all types.',
    hh_size = 'Area-weighted mean household size from the ACS block groups (people per household); defaults to 2.5.',
    vacancy_rate = 'Housing vacancy rate (fraction 0-1); flat 0.05 default in this model.',
    assessor_units = 'Dwelling units observed directly in the assessor sales data (Tier 1); NULL when absent.',
    residential_building_sqft = 'Residential building floor area from the dasymetric weights (sq ft).',
    land_development_category = 'Land development category from the dasymetric weights.',
    pop_dasym_weight = 'Population weight: dwelling units times household size (people).',
    hh_dasym_weight = 'Household weight: dwelling units times occupancy (households).',
    hh = 'Households: dwelling units times occupancy (households).'
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,)),
    assert_parcel_du_estimation_row_count(parcel_table := brewgis.@{region}.parcel_dasymetric_weights),
    assert_du_assessor_units_direct,
    assert_du_vacancy_rates
  ),
  blueprints @region_blueprints()
);

-- Dwelling Unit Estimation — 2-tier cascade using LightGBM regressor.
--
-- Tier 1: Direct assessor unit observation (from the region sales adapter —
--         Fresno's is empty, so Tier 1 falls through).
-- Tier 2: LightGBM regressor prediction (du_total_regressor from
--         @{region}.du_regressor, which reads features from
--         @{region}.parcel_dasymetric_weights).
-- Fallback: 0.0 (non-residential parcels).
--
-- Household size comes from ACS block groups via an area-weighted join of
-- the region assessor parcels (the county roll's per-APN geometry, which
-- covers the same parcel fabric parcel_shim carries).
--
-- Vacancy rate: flat 0.05 default.
--
-- Output:
--   du                     — final dwelling unit estimate (2-tier cascade)
--   vacancy_rate           — flat 0.05 default
--   household_size         — from ACS block group (area-weighted mean)
--   pop_dasym_weight       — du × household_size
--   hh_dasym_weight        — du × (1 - vacancy_rate)

WITH parcel_input AS (
    SELECT
        dw.apn,
        COALESCE(dr.du_detsf_sl, 0)::double precision AS du_detsf_sl_regressor,
        COALESCE(dr.du_detsf_ll, 0)::double precision AS du_detsf_ll_regressor,
        COALESCE(dr.du_attsf, 0)::double precision AS du_attsf_regressor,
        COALESCE(dr.du_mf2to4, 0)::double precision AS du_mf2to4_regressor,
        COALESCE(dr.du_mf5p, 0)::double precision AS du_mf5p_regressor,
        COALESCE(dr.du_total, 0)::double precision AS du_total_regressor,
        dw.lot_size_acres,
        dw.land_development_category,
        dw.residential_building_sqft,
        dw.intersection_density,
        dw.actual_living_sqft,
        dw.actual_building_sqft
    FROM brewgis.@{region}.parcel_dasymetric_weights dw
    LEFT JOIN brewgis.@{region}.du_regressor dr ON dw.apn = dr.apn
),

-- ── Assessor units (Tier 1 source; empty for regions without sales data) ──
assessor_units AS (
    SELECT
        apn,
        units,
        property_type
    FROM brewgis.@{region}.assessor_sales_deduped
),

-- ── ACS household size (area-weighted mean of hh/du over the parcel) ──────
acs_hh_size AS (
    SELECT
        ap.apn,
        NULLIF(
            SUM(
                a.hh / NULLIF(a.du, 0)
                * ST_Area(ST_Intersection(ap.local_geometry, a.local_envelope))
            ) / NULLIF(SUM(ST_Area(ST_Intersection(ap.local_geometry, a.local_envelope))), 0),
            0
        ) AS hh_size
    FROM brewgis.@{region}.assessor_parcels ap
    JOIN brewgis.@{region}.acs_block_group_projected a
        ON ST_Intersects(ap.local_geometry, a.geometry)
    GROUP BY ap.apn
),

-- ── Merge ACS hh_size and assessor units with APN-level data ──────────────
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
        au.units AS assessor_units,
        COALESCE(acs.hh_size, 2.5) AS hh_size
    FROM parcel_input p
    LEFT JOIN assessor_units au ON p.apn = au.apn
    LEFT JOIN acs_hh_size acs ON p.apn = acs.apn
),

-- ── 2-tier DU estimation cascade ──────────────────────────────────────────
-- Tier 1: Direct assessor observation (units from sales adapter)
-- Tier 2: LightGBM regressor prediction (du_total_regressor)
-- Fallback: 0.0
du_estimation AS (
    SELECT
        apn,
        COALESCE(
            assessor_units::double precision,
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
    (du * COALESCE(hh_size, 2.5))::double precision AS pop_dasym_weight,
    -- Household weight: du × (1 - vacancy_rate)
    (du * (1.0 - COALESCE(vacancy_rate, 0.05)))::double precision AS hh_dasym_weight,
    -- Households: du × (1 - vacancy_rate)
    (du * (1.0 - COALESCE(vacancy_rate, 0.05)))::double precision AS hh
FROM du_estimation;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_du_estimation_apn_')
  ON @this_model USING btree (apn);
  ANALYZE @this_model;

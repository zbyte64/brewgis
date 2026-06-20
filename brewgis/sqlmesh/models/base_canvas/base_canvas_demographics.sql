MODEL (
  name brewgis.base_canvas.base_canvas_demographics,
  kind FULL,
  audits (
    not_null(columns := (parcel_id)),
    assert_population_conserved
  )
);

-- Base Canvas Demographics — DU-weighted allocation from Census 2020 blocks.
--
-- For each parcel in base_canvas_geometry:
--   - Population: allocated from Census 2020 blocks using DU-weighted proportional
--     allocation (Section 5, Section 9 of methodology).
--   - Households: du × (1 - vacancy_rate)
--   - Dwelling units: from parcel_du_estimation (not allocated from ACS)
--   - Demographic averages (income, education, etc.): area-weighted mean from
--     ACS block groups.

WITH parcel_geom AS (
    SELECT
        bg.parcel_id,
        bg.geometry,
        bg.local_geometry,
        bg.county,
        bg.land_development_category,
        bg.built_form_key,
        bg.intersection_density,
        bg.area_gross,
        bg.area_gross_acres,
        bg.area_parcel_acres,
        bg.area_dev_condition_acres,
        bg.area_row_acres,
        bg.pop AS bg_pop,
        bg.hh AS bg_hh,
        bg.du AS bg_du,
        bg.bldg_area_detsf_sl,
        bg.bldg_area_detsf_ll,
        bg.bldg_area_attsf,
        bg.bldg_area_mf,
        bg.bldg_area_retail_services,
        bg.bldg_area_restaurant,
        bg.bldg_area_accommodation,
        bg.bldg_area_arts_entertainment,
        bg.bldg_area_other_services,
        bg.bldg_area_office_services,
        bg.bldg_area_public_admin,
        bg.bldg_area_education,
        bg.bldg_area_medical_services,
        bg.bldg_area_transport_warehousing,
        bg.bldg_area_wholesale,
        bg.land_use,
        bg.assessor_use_code,
        bg.residential_irrigated_area,
        bg.commercial_irrigated_area,
        bg.area_parcel_res,
        bg.area_parcel_emp_ag,
        bg.area_parcel_emp,
        bg.area_parcel_mixed_use,
        bg.area_parcel_no_use,
        bg.du_subtype,
        bg.is_residential,
        bg.residential_building_sqft,
        bg.commercial_building_sqft,
        bg.industrial_building_sqft,
        bg.other_building_sqft,
        bg.total_footprint_sqft,
        bg.building_count,
        bg.footprint_ratio,
        bg.max_levels,
        bg.dasym_impervious_fraction,
        bg.pop_dasym_weight,
        bg.emp_dasym_weight,
        bg.du_estimated,
        bg.hh_size,
        bg.vacancy_rate,
        bg.du_pop_dasym_weight,
        bg.hh_dasym_weight,
        bg.hh_estimated
    FROM brewgis.base_canvas.base_canvas_geometry bg
),



-- ── Spatial join: parcels → Census 2020 blocks ────────────────────────────
parcel_block_intersections AS (
    SELECT
        p.parcel_id,
        cb.geoid,
        cb.total_population,
        cb.total_housing_units,
        p.du_pop_dasym_weight,
        p.du_estimated,
        p.hh_size,
        p.vacancy_rate,
        p.hh_dasym_weight,
        ST_Area(ST_ClipByBox2D(p.local_geometry, cb.local_envelope)) AS intersect_area,
        -- Normalize intersect area to fraction of total parcel area
        CASE WHEN ST_Area(p.local_geometry) > 0
             THEN ST_Area(ST_ClipByBox2D(p.local_geometry, cb.local_envelope))
                  / NULLIF(ST_Area(p.local_geometry), 0)
             ELSE 1.0
        END AS intersect_fraction
    FROM parcel_geom p
    JOIN brewgis.staging.census_2020_block_projected cb ON ST_Intersects(p.geometry, cb.geometry)
),

-- ── Per-block total DU weight for proportional allocation ──────────────────
block_weighted_totals AS (
    SELECT
        geoid,
        SUM(COALESCE(du_pop_dasym_weight, 0)) AS block_total_du_weight
    FROM parcel_block_intersections
    GROUP BY geoid
),

-- ── DU-weighted population allocation ─────────────────────────────────────
pop_allocated AS (
    SELECT
        pbi.parcel_id,
        SUM(
            pbi.total_population
            * COALESCE(pbi.du_pop_dasym_weight, 0)
            / NULLIF(bwt.block_total_du_weight, 0)
        ) AS pop,
        -- DU from estimation (not allocated), with hh derived from du × (1-vacancy)
        AVG(pbi.du_estimated) AS du,
        AVG(pbi.du_estimated * (1.0 - COALESCE(pbi.vacancy_rate, 0.05))) AS hh,
        -- Household size for demographic weighted means
        1.0 AS weight
    FROM parcel_block_intersections pbi
    LEFT JOIN block_weighted_totals bwt ON pbi.geoid = bwt.geoid
    GROUP BY pbi.parcel_id
),

-- ── ACS area-weighted means for demographic averages ───────────────────────
parcel_acs_intersections AS (
    SELECT
        p.parcel_id,
        a.median_income,
        a.rent_burden_pct,
        a.pct_minority,
        a.pct_college_educated,
        a.cost_burden_pct,
        ST_Area(ST_ClipByBox2D(p.local_geometry, a.local_envelope)) AS intersect_area
    FROM parcel_geom p
    JOIN brewgis.assessor.acs_block_group_projected a ON ST_Intersects(p.local_geometry, a.geometry)
),

acs_allocated AS (
    SELECT
        pai.parcel_id,
        SUM(pai.median_income * pai.intersect_area) / NULLIF(SUM(pai.intersect_area), 0) AS median_income,
        SUM(pai.rent_burden_pct * pai.intersect_area) / NULLIF(SUM(pai.intersect_area), 0) AS rent_burden_pct,
        SUM(pai.pct_minority * pai.intersect_area) / NULLIF(SUM(pai.intersect_area), 0) AS pct_minority,
        SUM(pai.pct_college_educated * pai.intersect_area) / NULLIF(SUM(pai.intersect_area), 0) AS pct_college_educated,
        SUM(pai.cost_burden_pct * pai.intersect_area) / NULLIF(SUM(pai.intersect_area), 0) AS cost_burden_pct
    FROM parcel_acs_intersections pai
    GROUP BY pai.parcel_id
)

SELECT
    p.parcel_id,
    p.geometry,
    p.local_geometry,
    p.county,
    p.land_development_category,
    p.built_form_key,
    p.intersection_density,
    p.area_gross,
    p.area_gross_acres,
    p.area_parcel_acres,
    p.area_dev_condition_acres,
    p.area_row_acres,
    COALESCE(pa.pop, p.bg_pop) AS pop,
    0.0::double precision AS pop_groupquarter,
    COALESCE(pa.hh, p.bg_hh) AS hh,
    COALESCE(pa.du, p.bg_du) AS du,
    p.du_subtype,
    p.is_residential,
    p.residential_building_sqft,
    p.commercial_building_sqft,
    p.industrial_building_sqft,
    p.other_building_sqft,
    p.total_footprint_sqft,
    p.building_count,
    p.footprint_ratio,
    p.max_levels,
    p.dasym_impervious_fraction,
    p.pop_dasym_weight,
    p.emp_dasym_weight,
    p.du_estimated,
    p.hh_size,
    p.vacancy_rate,
    p.du_pop_dasym_weight,
    p.hh_dasym_weight,
    p.hh_estimated,
    NULL::double precision AS du_detsf,
    NULL::double precision AS du_detsf_sl,
    NULL::double precision AS du_detsf_ll,
    NULL::double precision AS du_attsf,
    NULL::double precision AS du_mf,
    NULL::double precision AS du_mf2to4,
    NULL::double precision AS du_mf5p,
    NULL::double precision AS emp,
    acs.median_income,
    acs.rent_burden_pct,
    acs.pct_minority,
    acs.pct_college_educated,
    acs.cost_burden_pct,
    p.bldg_area_detsf_sl,
    p.bldg_area_detsf_ll,
    p.bldg_area_attsf,
    p.bldg_area_mf,
    p.bldg_area_retail_services,
    p.bldg_area_restaurant,
    p.bldg_area_accommodation,
    p.bldg_area_arts_entertainment,
    p.bldg_area_other_services,
    p.bldg_area_office_services,
    p.bldg_area_public_admin,
    p.bldg_area_education,
    p.bldg_area_medical_services,
    p.bldg_area_transport_warehousing,
    p.bldg_area_wholesale,
    p.land_use,
    p.assessor_use_code,
    p.residential_irrigated_area,
    p.commercial_irrigated_area,
    p.area_parcel_res,
    p.area_parcel_emp_ag,
    p.area_parcel_emp,
    p.area_parcel_mixed_use,
    p.area_parcel_no_use
FROM parcel_geom p
LEFT JOIN pop_allocated pa ON p.parcel_id = pa.parcel_id
LEFT JOIN acs_allocated acs ON p.parcel_id = acs.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_base_canvas_demographics_geometry
  ON brewgis.base_canvas.base_canvas_demographics USING GIST (geometry);

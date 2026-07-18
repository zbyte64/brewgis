MODEL (
  name brewgis.base_canvas.base_canvas_combined,
  kind FULL,
  audits (
    not_null(columns := (parcel_id)),
    assert_population_conserved,
    assert_census_block_coverage,
    assert_employment_conserved,
    assert_commercial_sectors_use_commercial_sqft,
    assert_industrial_sectors_use_industrial_sqft,
    assert_bldg_area_employment_targeted
  )
);

-- Base Canvas Combined — single model replacing demographics + employment + attributes.
--
-- Merged to reduce duplicate seq scans of base_canvas_geometry (502K rows) from
-- 3 sequential FT passes (demographics → employment → attributes) down to 1
-- pass in the parcel_geom CTE.  The output columns and row semantics are
-- identical to the former base_canvas_attributes.

WITH
-- ── Single scan of base_canvas_geometry ─────────────────────────────────────
parcel_geom AS (
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
        bg.hh_estimated,
        scd.du_detsf_sl          AS du_detsf_sl_regressor,
        scd.du_detsf_ll          AS du_detsf_ll_regressor,
        scd.du_attsf             AS du_attsf_regressor,
        scd.du_mf2to4            AS du_mf2to4_regressor,
        scd.du_mf5p              AS du_mf5p_regressor,
        scd.du_total_regressor   AS du_total_regressor,
        scd.emp_ret_per_acre     AS emp_ret_per_acre_regressor,
        scd.emp_off_per_acre     AS emp_off_per_acre_regressor,
        scd.emp_pub_per_acre     AS emp_pub_per_acre_regressor,
        scd.emp_ind_per_acre     AS emp_ind_per_acre_regressor,
        scd.emp_ag_per_acre      AS emp_ag_per_acre_regressor
    FROM brewgis.base_canvas.base_canvas_geometry bg
    LEFT JOIN brewgis.comparison.sacog_comparison_dasymetric scd ON bg.parcel_id = scd.parcel_id
),

-- ── Step 1: Demographics — DU-weighted Census block allocation ──────────────
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
        CASE WHEN ST_Area(p.local_geometry) > 0
             THEN ST_Area(ST_ClipByBox2D(p.local_geometry, cb.local_envelope))
                  / NULLIF(ST_Area(p.local_geometry), 0)
             ELSE 1.0
        END AS intersect_fraction
    FROM parcel_geom p
    JOIN brewgis.staging.census_2020_block_projected cb ON ST_Intersects(p.geometry, cb.geometry)
),

block_weighted_totals AS (
    SELECT
        geoid,
        SUM(COALESCE(du_pop_dasym_weight, 0)) AS block_total_du_weight
    FROM parcel_block_intersections
    GROUP BY geoid
),

block_regressor_du AS (
    SELECT
        geoid,
        SUM(COALESCE(du_estimated, 0)) AS block_regressor_du
    FROM parcel_block_intersections
    GROUP BY geoid
),

pop_allocated AS (
    SELECT
        pbi.parcel_id,
        SUM(
            pbi.total_population
            * COALESCE(pbi.du_pop_dasym_weight, 0)
            / NULLIF(bwt.block_total_du_weight, 0)
        ) AS pop,
        SUM(
            pbi.du_estimated
            * pbi.total_housing_units
            / NULLIF(br.block_regressor_du, 0)
        ) AS du,
        SUM(
            pbi.du_estimated
            * pbi.total_housing_units
            / NULLIF(br.block_regressor_du, 0)
            * (1.0 - COALESCE(pbi.vacancy_rate, 0.05))
        ) AS hh,
        1.0 AS weight
    FROM parcel_block_intersections pbi
    LEFT JOIN block_weighted_totals bwt ON pbi.geoid = bwt.geoid
    LEFT JOIN block_regressor_du br ON pbi.geoid = br.geoid
    GROUP BY pbi.parcel_id
),

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
),

demographics_data AS (
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
        p.area_parcel_no_use,
        p.du_detsf_sl_regressor,
        p.du_detsf_ll_regressor,
        p.du_attsf_regressor,
        p.du_mf2to4_regressor,
        p.du_mf5p_regressor,
        p.du_total_regressor,
        p.emp_ret_per_acre_regressor,
        p.emp_off_per_acre_regressor,
        p.emp_pub_per_acre_regressor,
        p.emp_ind_per_acre_regressor,
        p.emp_ag_per_acre_regressor
    FROM parcel_geom p
    LEFT JOIN pop_allocated pa ON p.parcel_id = pa.parcel_id
    LEFT JOIN acs_allocated acs ON p.parcel_id = acs.parcel_id
),

-- ── Step 2: Employment — sector-constrained LEHD WAC allocation ─────────────
emp_intersections AS (
    SELECT
        p.parcel_id,
        w.geoid,
        p.built_form_key,
        p.land_development_category,
        p.commercial_building_sqft,
        p.industrial_building_sqft,
        p.other_building_sqft,
        COALESCE(p.emp_dasym_weight, 0) AS emp_dasy_weight,
        w.emp,
        w.emp_retail_services,
        w.emp_restaurant,
        w.emp_accommodation,
        w.emp_arts_entertainment,
        w.emp_other_services,
        w.emp_office_services,
        w.emp_medical_services,
        w.emp_public_admin,
        w.emp_education,
        w.emp_manufacturing,
        w.emp_wholesale,
        w.emp_transport_warehousing,
        w.emp_utilities,
        w.emp_construction,
        w.emp_agriculture,
        w.emp_extraction,
        w.emp_military,
        w.emp_ret,
        w.emp_off,
        w.emp_pub,
        w.emp_ind,
        w.emp_ag,
        -- Area for allocation weight computation
        COALESCE(p.area_parcel_emp, p.area_parcel_acres, p.area_gross_acres, p.area_gross, 0) AS alloc_area,
        -- Building intensity for allocation weight computation
        COALESCE(p.commercial_building_sqft, 0)
            + COALESCE(p.industrial_building_sqft, 0)
            + COALESCE(p.other_building_sqft, 0) AS total_emp_bldg_sqft,
        -- Category-specific employment allocation weights
        -- Formula: area * (sqft_intensity + 1 floor) * predicted_per_acre_rate
        -- The +1 floor prevents zero-weight for parcels with non-zero rates but
        -- zero recorded building sqft.
        -- Gate on commercial_building_sqft or emp_dasym_weight to satisfy
        -- assert_commercial_sectors_use_commercial_sqft audit.
        GREATEST(0,
            COALESCE(p.area_parcel_emp, p.area_parcel_acres, p.area_gross_acres, p.area_gross, 0)
            * (COALESCE(p.commercial_building_sqft, 0)
               + COALESCE(p.industrial_building_sqft, 0)
               + COALESCE(p.other_building_sqft, 0) + 1)
            * COALESCE(p.emp_ret_per_acre_regressor, 0)
            * CASE WHEN COALESCE(p.commercial_building_sqft, 0) > 0 OR COALESCE(p.emp_dasym_weight, 0) > 0 THEN 1.0 ELSE 0.0 END
        ) AS emp_ret_alloc_weight,
        GREATEST(0,
            COALESCE(p.area_parcel_emp, p.area_parcel_acres, p.area_gross_acres, p.area_gross, 0)
            * (COALESCE(p.commercial_building_sqft, 0)
               + COALESCE(p.industrial_building_sqft, 0)
               + COALESCE(p.other_building_sqft, 0) + 1)
            * COALESCE(p.emp_off_per_acre_regressor, 0)
            * CASE WHEN COALESCE(p.commercial_building_sqft, 0) > 0 OR COALESCE(p.emp_dasym_weight, 0) > 0 THEN 1.0 ELSE 0.0 END
        ) AS emp_off_alloc_weight,
        GREATEST(0,
            COALESCE(p.area_parcel_emp, p.area_parcel_acres, p.area_gross_acres, p.area_gross, 0)
            * (COALESCE(p.commercial_building_sqft, 0)
               + COALESCE(p.industrial_building_sqft, 0)
               + COALESCE(p.other_building_sqft, 0) + 1)
            * COALESCE(p.emp_pub_per_acre_regressor, 0)
        ) AS emp_pub_alloc_weight,
        GREATEST(0,
            COALESCE(p.area_parcel_emp, p.area_parcel_acres, p.area_gross_acres, p.area_gross, 0)
            * (COALESCE(p.commercial_building_sqft, 0)
               + COALESCE(p.industrial_building_sqft, 0)
               + COALESCE(p.other_building_sqft, 0) + 1)
            * COALESCE(p.emp_ind_per_acre_regressor, 0)
            * CASE WHEN COALESCE(p.industrial_building_sqft, 0) > 0 OR COALESCE(p.emp_dasym_weight, 0) > 0 THEN 1.0 ELSE 0.0 END
        ) AS emp_ind_alloc_weight,
        GREATEST(0,
            COALESCE(p.area_parcel_emp, p.area_parcel_acres, p.area_gross_acres, p.area_gross, 0)
            * (COALESCE(p.commercial_building_sqft, 0)
               + COALESCE(p.industrial_building_sqft, 0)
               + COALESCE(p.other_building_sqft, 0) + 1)
            * COALESCE(p.emp_ag_per_acre_regressor, 0)
        ) AS emp_ag_alloc_weight,
        p.area_gross
    FROM demographics_data p
    JOIN brewgis.staging.wac_block_projected w ON ST_Intersects(p.geometry, w.geometry)
),

emp_block_weight_totals AS (
    SELECT
        geoid,
        SUM(COALESCE(emp_ret_alloc_weight, 0)) AS block_ret_weight,
        SUM(COALESCE(emp_off_alloc_weight, 0)) AS block_off_weight,
        SUM(COALESCE(emp_pub_alloc_weight, 0)) AS block_pub_weight,
        SUM(COALESCE(emp_ind_alloc_weight, 0)) AS block_ind_weight,
        SUM(COALESCE(emp_ag_alloc_weight, 0)) AS block_ag_weight,
        SUM(COALESCE(emp_ret_alloc_weight, 0) + COALESCE(emp_off_alloc_weight, 0)
            + COALESCE(emp_pub_alloc_weight, 0) + COALESCE(emp_ind_alloc_weight, 0)
            + COALESCE(emp_ag_alloc_weight, 0)) AS block_total_weight
    FROM emp_intersections
    GROUP BY geoid
),

emp_allocated AS (
    SELECT
        ei.parcel_id,
        -- Total employment: use combined weight across all categories
        SUM(ei.emp * (COALESCE(ei.emp_ret_alloc_weight, 0) + COALESCE(ei.emp_off_alloc_weight, 0)
            + COALESCE(ei.emp_pub_alloc_weight, 0) + COALESCE(ei.emp_ind_alloc_weight, 0)
            + COALESCE(ei.emp_ag_alloc_weight, 0))
            / NULLIF(bwt.block_total_weight, 0)) AS emp,
        -- Aggregate categories → matching weight, falling back to total weight when category weight is zero
        SUM(ei.emp_ret * COALESCE(ei.emp_ret_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ret_weight, 0) > 0 THEN bwt.block_ret_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_ret,
        SUM(ei.emp_off * COALESCE(ei.emp_off_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_off_weight, 0) > 0 THEN bwt.block_off_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_off,
        SUM(ei.emp_pub * COALESCE(ei.emp_pub_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_pub_weight, 0) > 0 THEN bwt.block_pub_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_pub,
        SUM(ei.emp_ind * COALESCE(ei.emp_ind_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ind_weight, 0) > 0 THEN bwt.block_ind_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_ind,
        SUM(ei.emp_ag * COALESCE(ei.emp_ag_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ag_weight, 0) > 0 THEN bwt.block_ag_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_ag,
        -- Detailed retail sub-categories → parent retail weight with fallback
        SUM(ei.emp_retail_services * COALESCE(ei.emp_ret_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ret_weight, 0) > 0 THEN bwt.block_ret_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_retail_services,
        SUM(ei.emp_restaurant * COALESCE(ei.emp_ret_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ret_weight, 0) > 0 THEN bwt.block_ret_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_restaurant,
        SUM(ei.emp_accommodation * COALESCE(ei.emp_ret_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ret_weight, 0) > 0 THEN bwt.block_ret_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_accommodation,
        SUM(ei.emp_arts_entertainment * COALESCE(ei.emp_ret_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ret_weight, 0) > 0 THEN bwt.block_ret_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_arts_entertainment,
        SUM(ei.emp_other_services * COALESCE(ei.emp_ret_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ret_weight, 0) > 0 THEN bwt.block_ret_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_other_services,
        -- Detailed office sub-categories → parent office weight with fallback
        SUM(ei.emp_office_services * COALESCE(ei.emp_off_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_off_weight, 0) > 0 THEN bwt.block_off_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_office_services,
        SUM(ei.emp_medical_services * COALESCE(ei.emp_off_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_off_weight, 0) > 0 THEN bwt.block_off_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_medical_services,
        -- Detailed public sub-categories → parent public weight with fallback
        SUM(ei.emp_public_admin * COALESCE(ei.emp_pub_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_pub_weight, 0) > 0 THEN bwt.block_pub_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_public_admin,
        SUM(ei.emp_education * COALESCE(ei.emp_pub_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_pub_weight, 0) > 0 THEN bwt.block_pub_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_education,
        -- Detailed industrial sub-categories → parent industrial weight with fallback
        SUM(ei.emp_manufacturing * COALESCE(ei.emp_ind_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ind_weight, 0) > 0 THEN bwt.block_ind_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_manufacturing,
        SUM(ei.emp_wholesale * COALESCE(ei.emp_ind_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ind_weight, 0) > 0 THEN bwt.block_ind_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_wholesale,
        SUM(ei.emp_transport_warehousing * COALESCE(ei.emp_ind_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ind_weight, 0) > 0 THEN bwt.block_ind_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_transport_warehousing,
        SUM(ei.emp_utilities * COALESCE(ei.emp_ind_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ind_weight, 0) > 0 THEN bwt.block_ind_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_utilities,
        SUM(ei.emp_construction * COALESCE(ei.emp_ind_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ind_weight, 0) > 0 THEN bwt.block_ind_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_construction,
        -- Detailed ag sub-categories → parent ag weight with fallback
        SUM(ei.emp_agriculture * COALESCE(ei.emp_ag_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ag_weight, 0) > 0 THEN bwt.block_ag_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_agriculture,
        SUM(ei.emp_extraction * COALESCE(ei.emp_ag_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_ag_weight, 0) > 0 THEN bwt.block_ag_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_extraction,
        -- Military: use public weight with fallback
        SUM(ei.emp_military * COALESCE(ei.emp_pub_alloc_weight, 0)
            / CASE WHEN COALESCE(bwt.block_pub_weight, 0) > 0 THEN bwt.block_pub_weight ELSE NULLIF(COALESCE(bwt.block_total_weight, 0), 0) END
        ) AS emp_military
    FROM emp_intersections ei
    LEFT JOIN emp_block_weight_totals bwt ON ei.geoid = bwt.geoid
    GROUP BY ei.parcel_id
),

employment_data AS (
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
        p.pop,
        p.pop_groupquarter,
        p.hh,
        p.du,
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
        p.median_income,
        p.rent_burden_pct,
        p.pct_minority,
        p.pct_college_educated,
        p.cost_burden_pct,
        p.vacancy_rate AS vacancy_rate_demo,
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
        p.area_parcel_no_use,
        p.du_detsf_sl_regressor,
        p.du_detsf_ll_regressor,
        p.du_attsf_regressor,
        p.du_mf2to4_regressor,
        p.du_mf5p_regressor,
        p.du_total_regressor,
        COALESCE(a.emp, 0.0) AS emp,
        COALESCE(a.emp_retail_services, 0) + COALESCE(a.emp_restaurant, 0)
            + COALESCE(a.emp_accommodation, 0) + COALESCE(a.emp_arts_entertainment, 0)
            + COALESCE(a.emp_other_services, 0) AS emp_ret,
        a.emp_retail_services,
        a.emp_restaurant,
        a.emp_accommodation,
        a.emp_arts_entertainment,
        a.emp_other_services,
        COALESCE(a.emp_office_services, 0) + COALESCE(a.emp_medical_services, 0) AS emp_off,
        a.emp_office_services,
        a.emp_medical_services,
        COALESCE(a.emp_public_admin, 0) + COALESCE(a.emp_education, 0) AS emp_pub,
        a.emp_public_admin,
        a.emp_education,
        COALESCE(a.emp_manufacturing, 0) + COALESCE(a.emp_wholesale, 0)
            + COALESCE(a.emp_transport_warehousing, 0) + COALESCE(a.emp_utilities, 0)
            + COALESCE(a.emp_construction, 0) AS emp_ind,
        a.emp_manufacturing,
        a.emp_wholesale,
        a.emp_transport_warehousing,
        a.emp_utilities,
        a.emp_construction,
        COALESCE(a.emp_agriculture, 0) AS emp_ag,
        a.emp_agriculture,
        a.emp_extraction,
        a.emp_military
    FROM demographics_data p
    LEFT JOIN emp_allocated a ON p.parcel_id = a.parcel_id
),

-- ── Step 3: Attributes — calibration, building areas, land use, irrigation ──
calibration AS (
    SELECT * FROM brewgis.seeds.calibration_parameters
),

assessor_codes AS (
    SELECT use_code, category FROM brewgis.seeds.assessor_use_codes
),

sacog_use AS (
    SELECT land_use_label, category FROM brewgis.seeds.sacog_land_use
),

with_cal AS (
    SELECT
        s.*,
        COALESCE(NULLIF(s.land_development_category, ''), 'urban') AS lc_key,
        c.sqft_per_du,
        c.sqft_per_emp_retail,
        c.sqft_per_emp_office,
        c.sqft_per_emp_public,
        c.sqft_per_emp_industrial,
        c.res_irrigation_frac,
        c.com_irrigation_frac,
        c.intersection_density AS calib_int_density
    FROM employment_data s
    LEFT JOIN calibration c
        ON COALESCE(NULLIF(s.land_development_category, ''), 'urban') = c.land_development_category
),

demographics_attr AS (
    SELECT
        *,
        COALESCE(pop_groupquarter, 0.0) AS pop_groupquarter_v,
        COALESCE(du_detsf_sl_regressor, 0.0) AS du_detsf_sl_v,
        COALESCE(du_detsf_ll_regressor, 0.0) AS du_detsf_ll_v,
        COALESCE(du_detsf_sl_regressor, 0.0) + COALESCE(du_detsf_ll_regressor, 0.0) AS du_detsf_v,
        COALESCE(du_attsf_regressor, 0.0) AS du_attsf_v,
        COALESCE(du_mf2to4_regressor, 0.0) AS du_mf2to4_v,
        COALESCE(du_mf5p_regressor, 0.0) AS du_mf5p_v,
        COALESCE(du_mf2to4_regressor, 0.0) + COALESCE(du_mf5p_regressor, 0.0) AS du_mf_v,
        GREATEST(0, COALESCE(emp_ret, emp * 0.302)) AS emp_ret_v,
        GREATEST(0, COALESCE(emp_off, emp * 0.478)) AS emp_off_v,
        GREATEST(0, COALESCE(emp_pub, emp * 0.082)) AS emp_pub_v,
        GREATEST(0, COALESCE(emp_ind, emp * 0.138)) AS emp_ind_v,
        COALESCE(emp_retail_services, emp_ret * COALESCE(f.emp_retail_services_frac, 0.466)) AS emp_retail_services_v,
        COALESCE(emp_restaurant, emp_ret * COALESCE(f.emp_restaurant_frac, 0.259)) AS emp_restaurant_v,
        COALESCE(emp_accommodation, emp_ret * COALESCE(f.emp_accommodation_frac, 0.023)) AS emp_accommodation_v,
        COALESCE(emp_arts_entertainment, emp_ret * COALESCE(f.emp_arts_entertainment_frac, 0.046)) AS emp_arts_entertainment_v,
        COALESCE(emp_other_services, emp_ret * COALESCE(f.emp_other_services_frac, 0.203)) AS emp_other_services_v,
        COALESCE(emp_office_services, emp_off * COALESCE(f.emp_office_services_frac, 0.912)) AS emp_office_services_v,
        COALESCE(emp_medical_services, emp_off * COALESCE(f.emp_medical_services_frac, 0.088)) AS emp_medical_services_v,
        COALESCE(emp_public_admin, emp_pub * COALESCE(f.emp_public_admin_frac, 0.382)) AS emp_public_admin_v,
        COALESCE(emp_education, emp_pub * COALESCE(f.emp_education_frac, 0.618)) AS emp_education_v,
        COALESCE(emp_manufacturing, emp_ind * COALESCE(f.emp_manufacturing_frac, 0.619)) AS emp_manufacturing_v,
        COALESCE(emp_wholesale, emp_ind * COALESCE(f.emp_wholesale_frac, 0.143)) AS emp_wholesale_v,
        COALESCE(emp_transport_warehousing, emp_ind * COALESCE(f.emp_transport_warehousing_frac, 0.190)) AS emp_transport_warehousing_v,
        COALESCE(emp_utilities, emp_ind * COALESCE(f.emp_utilities_frac, 0.010)) AS emp_utilities_v,
        COALESCE(emp_construction, emp_ind * COALESCE(f.emp_construction_frac, 0.038)) AS emp_construction_v,
        COALESCE(emp_agriculture, emp_ag * COALESCE(f.emp_agriculture_frac, 0.7)) AS emp_agriculture_v,
        COALESCE(emp_extraction, emp_ag * COALESCE(f.emp_extraction_frac, 0.3)) AS emp_extraction_v
    FROM with_cal
    LEFT JOIN brewgis.staging.wac_sub_sector_fallbacks f ON TRUE
),

building_areas AS (
    SELECT
        *,
        COALESCE(
            bldg_area_detsf_sl,
            du_detsf_sl_v * COALESCE(sqft_per_du, 3000.0)
        ) AS bldg_area_detsf_sl_v,
        COALESCE(
            bldg_area_detsf_ll,
            du_detsf_ll_v * COALESCE(sqft_per_du, 3000.0)
        ) AS bldg_area_detsf_ll_v,
        COALESCE(
            bldg_area_attsf,
            du_attsf_v * COALESCE(sqft_per_du, 1500.0)
        ) AS bldg_area_attsf_v,
        COALESCE(
            bldg_area_mf,
            du_mf_v * 1500.0,
            du_mf_v * 800.0
        ) AS bldg_area_mf_v,
        COALESCE(
            bldg_area_retail_services,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_retail_services_v, 0) / NULLIF(COALESCE(emp_ret_v, 0), 0)
            END,
            emp_retail_services_v * COALESCE(sqft_per_emp_retail, 706.0)
        ) AS bldg_area_retail_services_v,
        COALESCE(
            bldg_area_restaurant,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_restaurant_v, 0) / NULLIF(COALESCE(emp_ret_v, 0), 0)
            END,
            emp_restaurant_v * COALESCE(sqft_per_emp_retail, 706.0)
        ) AS bldg_area_restaurant_v,
        COALESCE(
            bldg_area_accommodation,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_accommodation_v, 0) / NULLIF(COALESCE(emp_ret_v, 0), 0)
            END,
            emp_accommodation_v * COALESCE(sqft_per_emp_retail, 706.0)
        ) AS bldg_area_accommodation_v,
        COALESCE(
            bldg_area_arts_entertainment,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_arts_entertainment_v, 0) / NULLIF(COALESCE(emp_ret_v, 0), 0)
            END,
            emp_arts_entertainment_v * COALESCE(sqft_per_emp_retail, 706.0)
        ) AS bldg_area_arts_entertainment_v,
        COALESCE(
            bldg_area_other_services,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_other_services_v, 0) / NULLIF(COALESCE(emp_ret_v, 0), 0)
            END,
            emp_other_services_v * COALESCE(sqft_per_emp_retail, 706.0)
        ) AS bldg_area_other_services_v,
        COALESCE(
            bldg_area_office_services,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_office_services_v, 0) / NULLIF(COALESCE(emp_off_v, 0), 0)
            END,
            emp_office_services_v * COALESCE(sqft_per_emp_office, 408.0)
        ) AS bldg_area_office_services_v,
        COALESCE(
            bldg_area_public_admin,
            CASE WHEN other_building_sqft > 0
                THEN other_building_sqft * COALESCE(emp_public_admin_v, 0) / NULLIF(COALESCE(emp_pub_v, 0), 0)
            END,
            emp_public_admin_v * COALESCE(sqft_per_emp_public, 909.0)
        ) AS bldg_area_public_admin_v,
        COALESCE(
            bldg_area_education,
            CASE WHEN other_building_sqft > 0
                THEN other_building_sqft * COALESCE(emp_education_v, 0) / NULLIF(COALESCE(emp_pub_v, 0), 0)
            END,
            emp_education_v * COALESCE(sqft_per_emp_public, 909.0)
        ) AS bldg_area_education_v,
        COALESCE(
            bldg_area_medical_services,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_medical_services_v, 0) / NULLIF(COALESCE(emp_off_v, 0), 0)
            END,
            emp_medical_services_v * COALESCE(sqft_per_emp_office, 408.0)
        ) AS bldg_area_medical_services_v,
        COALESCE(
            bldg_area_transport_warehousing,
            CASE WHEN industrial_building_sqft > 0
                THEN industrial_building_sqft * COALESCE(emp_transport_warehousing_v, 0) / NULLIF(COALESCE(emp_ind_v, 0), 0)
            END,
            emp_transport_warehousing_v * COALESCE(sqft_per_emp_industrial, 267.0)
        ) AS bldg_area_transport_warehousing_v,
        COALESCE(
            bldg_area_wholesale,
            CASE WHEN industrial_building_sqft > 0
                THEN industrial_building_sqft * COALESCE(emp_wholesale_v, 0) / NULLIF(COALESCE(emp_ind_v, 0), 0)
            END,
            emp_wholesale_v * COALESCE(sqft_per_emp_industrial, 267.0)
        ) AS bldg_area_wholesale_v
    FROM demographics_attr
),

overture_lu AS (
    SELECT parcel_id, overture_category
    FROM brewgis.assessor.overture_land_use_parcel
),

classified AS (
    SELECT
        b.*,
        COALESCE(
            NULLIF(b.land_development_category, ''),
            ac.category,
            su.category,
            olu.overture_category,
            'urban'
        ) AS lnd_v,
        COALESCE(NULLIF(b.built_form_key, ''), 'mixed_use') AS bf_v
    FROM building_areas b
    LEFT JOIN assessor_codes ac
        ON LEFT(COALESCE(b.assessor_use_code, ''), 2) = ac.use_code::text
    LEFT JOIN sacog_use su
        ON TRIM(COALESCE(b.land_use, '')) = su.land_use_label
    LEFT JOIN overture_lu olu
        ON b.parcel_id = olu.parcel_id
),

area_by_use AS (
    SELECT
        *,
        lnd_v AS lnd_category,
        bf_v AS bf_key,
        CASE
            WHEN COALESCE(du_total_regressor, 0) > 0
                 AND COALESCE(residential_building_sqft, 0) > 0
                 AND lnd_v IN ('urban', 'mixed_use')
                THEN COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0)
            WHEN lnd_v IN ('industrial', 'agricultural', 'undeveloped') THEN 0
            WHEN lnd_v IN ('urban', 'mixed_use')
                 AND COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                     + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0) > 0
                 AND (COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                      + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0))
                     / NULLIF(COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0) * 43560, 0) >= 0.05
                 THEN COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0)
                      * COALESCE(residential_building_sqft, 0)
                        / NULLIF(COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                                 + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0), 0)
            WHEN lnd_v IN ('urban', 'mixed_use') THEN 0
            ELSE area_parcel_res
        END AS area_parcel_res_v,
        CASE WHEN lnd_v = 'agricultural'
            THEN COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0) ELSE area_parcel_emp_ag END AS area_parcel_emp_ag_v,
        CASE
            WHEN COALESCE(du_total_regressor, 0) > 0
                 AND COALESCE(residential_building_sqft, 0) > 0
                 AND lnd_v IN ('urban', 'mixed_use')
                THEN 0
            WHEN COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                 + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0) > 0
                 AND (COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                      + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0))
                     / NULLIF(COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0) * 43560, 0) >= 0.05
                 THEN COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0)
                      * COALESCE(commercial_building_sqft + industrial_building_sqft + other_building_sqft, 0)
                        / NULLIF(COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                                 + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0), 0)
            WHEN lnd_v = 'industrial' THEN COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0)
            WHEN lnd_v IN ('urban', 'mixed_use') THEN 0
            WHEN lnd_v IN ('agricultural', 'undeveloped') THEN 0
            ELSE COALESCE(area_parcel_emp, 0)
        END AS area_parcel_emp_v,
        CASE WHEN lnd_v = 'mixed_use'
            THEN COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0) ELSE area_parcel_mixed_use END AS area_parcel_mixed_use_v,
        CASE
            WHEN COALESCE(du_total_regressor, 0) > 0
                 AND COALESCE(residential_building_sqft, 0) > 0
                 AND lnd_v IN ('urban', 'mixed_use')
                THEN 0
            WHEN COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                 + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0) > 0
                 AND (COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                      + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0))
                     / NULLIF(COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0) * 43560, 0) >= 0.05
                 THEN 0
            WHEN lnd_v IN ('urban', 'mixed_use') THEN COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0)
            WHEN lnd_v = 'undeveloped' THEN COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0)
            ELSE area_parcel_no_use
        END AS area_parcel_no_use_v
    FROM classified
),

nlcd_data AS (
    SELECT
        n.parcel_id,
        n.impervious_fraction,
        tc.tree_canopy_fraction
    FROM brewgis.nlcd.nlcd_parcel_stats n
    LEFT JOIN brewgis.nlcd.nlcd_tree_canopy_parcel_stats tc
        ON n.parcel_id = tc.parcel_id
),

irrigation AS (
    SELECT
        abu.*,
        nlcd.impervious_fraction,
        nlcd.tree_canopy_fraction,
        COALESCE(abu.residential_irrigated_area,
            COALESCE(abu.area_parcel_res_v, abu.area_gross_acres, abu.area_gross, 0)
                * COALESCE(NULLIF(nlcd.impervious_fraction, 0), NULLIF(abu.dasym_impervious_fraction, 0), abu.res_irrigation_frac, 0.064)
        ) AS residential_irrigated_area_v,
        COALESCE(abu.commercial_irrigated_area,
            COALESCE(abu.area_parcel_emp_v, abu.area_gross_acres, abu.area_gross, 0)
                * COALESCE(NULLIF(nlcd.impervious_fraction, 0), NULLIF(abu.dasym_impervious_fraction, 0), abu.com_irrigation_frac, 0.035)
        ) AS commercial_irrigated_area_v
    FROM area_by_use abu
    LEFT JOIN nlcd_data nlcd ON abu.parcel_id = nlcd.parcel_id
),

with_intersection AS (
    SELECT
        i.*,
        ROUND(COALESCE(
            @IF(@osm_intersection_table <> '',
                NULLIF(osm.intersection_density, 0),
            ),
            NULLIF(i.intersection_density, 0),
            COALESCE(calib_int_density, 12.5)
        )::numeric, 2) AS int_dens_v
    FROM irrigation i
    LEFT @JOIN(@osm_intersection_table)
        public.@{osm_intersection_table} osm ON i.parcel_id = osm.parcel_id
)

-- Final output — same columns as the former base_canvas_attributes
SELECT
    parcel_id,
    geometry,
    local_geometry,
    county,
    lnd_category AS land_development_category,
    bf_key AS built_form_key,
    int_dens_v AS intersection_density,
    area_gross,
    area_gross_acres,
    area_parcel_acres,
    area_dev_condition_acres,
    area_row_acres,
    area_parcel_res_v AS area_parcel_res,
    area_parcel_res_v AS area_parcel_res_acres,
    area_parcel_emp_ag_v AS area_parcel_emp_ag,
    area_parcel_emp_ag_v AS area_parcel_emp_ag_acres,
    area_parcel_emp_v AS area_parcel_emp,
    area_parcel_emp_v AS area_parcel_emp_acres,
    area_parcel_mixed_use_v AS area_parcel_mixed_use,
    area_parcel_mixed_use_v AS area_parcel_mixed_use_acres,
    area_parcel_no_use_v AS area_parcel_no_use,
    area_parcel_no_use_v AS area_parcel_no_use_acres,
    COALESCE(pop, 0.0) AS pop,
    pop_groupquarter_v AS pop_groupquarter,
    COALESCE(hh, 0.0) AS hh,
    COALESCE(du, 0.0) AS du,
    du_estimated,
    du_detsf_v AS du_detsf,
    du_detsf_sl_v AS du_detsf_sl,
    du_detsf_ll_v AS du_detsf_ll,
    du_attsf_v AS du_attsf,
    du_mf_v AS du_mf,
    du_mf2to4_v AS du_mf2to4,
    du_mf5p_v AS du_mf5p,
    du_subtype,
    is_residential,
    residential_building_sqft,
    commercial_building_sqft,
    industrial_building_sqft,
    other_building_sqft,
    total_footprint_sqft,
    building_count,
    footprint_ratio,
    max_levels,
    emp_dasym_weight,
    COALESCE(emp, 0.0) AS emp,
    emp_ret_v AS emp_ret,
    emp_off_v AS emp_off,
    emp_pub_v AS emp_pub,
    emp_ind_v AS emp_ind,
    emp_ag AS emp_ag,
    emp_military AS emp_military,
    emp_retail_services_v AS emp_retail_services,
    emp_restaurant_v AS emp_restaurant,
    emp_accommodation_v AS emp_accommodation,
    emp_arts_entertainment_v AS emp_arts_entertainment,
    emp_other_services_v AS emp_other_services,
    emp_office_services_v AS emp_office_services,
    emp_medical_services_v AS emp_medical_services,
    emp_public_admin_v AS emp_public_admin,
    emp_education_v AS emp_education,
    emp_manufacturing_v AS emp_manufacturing,
    emp_wholesale_v AS emp_wholesale,
    emp_transport_warehousing_v AS emp_transport_warehousing,
    emp_utilities_v AS emp_utilities,
    emp_construction_v AS emp_construction,
    emp_agriculture_v AS emp_agriculture,
    emp_extraction_v AS emp_extraction,
    bldg_area_detsf_sl_v AS bldg_area_detsf_sl,
    bldg_area_detsf_ll_v AS bldg_area_detsf_ll,
    bldg_area_attsf_v AS bldg_area_attsf,
    bldg_area_mf_v AS bldg_area_mf,
    bldg_area_retail_services_v AS bldg_area_retail_services,
    bldg_area_restaurant_v AS bldg_area_restaurant,
    bldg_area_accommodation_v AS bldg_area_accommodation,
    bldg_area_arts_entertainment_v AS bldg_area_arts_entertainment,
    bldg_area_other_services_v AS bldg_area_other_services,
    bldg_area_office_services_v AS bldg_area_office_services,
    bldg_area_public_admin_v AS bldg_area_public_admin,
    bldg_area_education_v AS bldg_area_education,
    bldg_area_medical_services_v AS bldg_area_medical_services,
    bldg_area_transport_warehousing_v AS bldg_area_transport_warehousing,
    bldg_area_wholesale_v AS bldg_area_wholesale,
    residential_irrigated_area_v AS residential_irrigated_area,
    commercial_irrigated_area_v AS commercial_irrigated_area,
    median_income,
    rent_burden_pct,
    pct_minority,
    pct_college_educated,
    cost_burden_pct,
    tree_canopy_fraction,
    vacancy_rate,
    du_pop_dasym_weight,
    ROUND((du * (1.0 - COALESCE(vacancy_rate, 0.0)))::numeric, 2) AS occupied_du
FROM with_intersection;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_base_canvas_combined_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_base_canvas_combined_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;

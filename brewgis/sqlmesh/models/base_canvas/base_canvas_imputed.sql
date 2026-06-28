MODEL (
  name brewgis.base_canvas.base_canvas_imputed,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  audits (
    not_null(columns := (parcel_id))
  )
);

-- Base Canvas Imputed — three-tier imputation cascade.
--
-- Tier 1: Direct value from base_canvas_attributes (preserves existing values)
-- Tier 2: County average for remaining NULLs (window function)
-- Tier 3: National default constant as final fallback
-- Always treat 0 as 0, NULLs are what we fill in.

WITH attributes AS (
    SELECT * FROM brewgis.base_canvas.base_canvas_attributes
),

-- Tier 2: County averages for key numeric columns
regional_avg AS (
    SELECT
        county,
        AVG(pop) AS county_avg_pop,
        AVG(hh) AS county_avg_hh,
        AVG(du) AS county_avg_du,
        AVG(emp) AS county_avg_emp,
        AVG(intersection_density) AS county_avg_int_density
    FROM attributes
    GROUP BY county
),

-- County average DU sub-type proportions for imputation
du_subtype_proportions AS (
    SELECT
        county,
        SUM(du_detsf_sl) / NULLIF(SUM(du), 0) AS pct_detsf_sl,
        SUM(du_detsf_ll) / NULLIF(SUM(du), 0) AS pct_detsf_ll,
        SUM(du_attsf) / NULLIF(SUM(du), 0) AS pct_attsf,
        SUM(du_mf2to4) / NULLIF(SUM(du), 0) AS pct_mf2to4,
        SUM(du_mf5p) / NULLIF(SUM(du), 0) AS pct_mf5p
    FROM attributes
    WHERE du > 0 AND du_detsf_sl IS NOT NULL
    GROUP BY county
)

SELECT
    a.parcel_id,
    a.geometry,
    a.local_geometry,
    a.county,
    a.land_development_category,
    a.built_form_key,
    ROUND(COALESCE(
        a.intersection_density,
        r.county_avg_int_density,
        12.5
    )::numeric, 2) AS intersection_density,
    a.area_gross,
    a.area_gross_acres,
    a.area_parcel_acres,
    a.area_dev_condition_acres,
    a.area_row_acres,
    a.area_parcel_res,
    a.area_parcel_res_acres,
    a.area_parcel_emp_ag,
    a.area_parcel_emp_ag_acres,
    a.area_parcel_emp,
    a.area_parcel_emp_acres,
    a.area_parcel_mixed_use,
    a.area_parcel_mixed_use_acres,
    a.area_parcel_no_use,
    a.area_parcel_no_use_acres,
    COALESCE(a.pop, r.county_avg_pop, 0.0) AS pop,
    COALESCE(a.pop_groupquarter, 0.0) AS pop_groupquarter,
    COALESCE(a.hh, r.county_avg_hh, 0.0) AS hh,
    COALESCE(a.du, r.county_avg_du, 0.0) AS du,
    COALESCE(a.du_detsf, dp.pct_detsf_sl * COALESCE(a.du, r.county_avg_du, 0.0)
        + dp.pct_detsf_ll * COALESCE(a.du, r.county_avg_du, 0.0), 0.0) AS du_detsf,
    CASE
        WHEN a.du IS NOT NULL AND a.du > 0
             AND COALESCE(a.du_detsf_sl, 0) = 0 AND COALESCE(a.du_detsf_ll, 0) = 0
             AND COALESCE(a.du_attsf, 0) = 0 AND COALESCE(a.du_mf2to4, 0) = 0
             AND COALESCE(a.du_mf5p, 0) = 0
        THEN COALESCE(dp.pct_detsf_sl * a.du, 0.0)
        ELSE COALESCE(a.du_detsf_sl, dp.pct_detsf_sl * COALESCE(a.du, r.county_avg_du, 0.0), 0.0)
    END AS du_detsf_sl,
    CASE
        WHEN a.du IS NOT NULL AND a.du > 0
             AND COALESCE(a.du_detsf_sl, 0) = 0 AND COALESCE(a.du_detsf_ll, 0) = 0
             AND COALESCE(a.du_attsf, 0) = 0 AND COALESCE(a.du_mf2to4, 0) = 0
             AND COALESCE(a.du_mf5p, 0) = 0
        THEN COALESCE(dp.pct_detsf_ll * a.du, 0.0)
        ELSE COALESCE(a.du_detsf_ll, dp.pct_detsf_ll * COALESCE(a.du, r.county_avg_du, 0.0), 0.0)
    END AS du_detsf_ll,
    CASE
        WHEN a.du IS NOT NULL AND a.du > 0
             AND COALESCE(a.du_detsf_sl, 0) = 0 AND COALESCE(a.du_detsf_ll, 0) = 0
             AND COALESCE(a.du_attsf, 0) = 0 AND COALESCE(a.du_mf2to4, 0) = 0
             AND COALESCE(a.du_mf5p, 0) = 0
        THEN COALESCE(dp.pct_attsf * a.du, 0.0)
        ELSE COALESCE(a.du_attsf, dp.pct_attsf * COALESCE(a.du, r.county_avg_du, 0.0), 0.0)
    END AS du_attsf,
    COALESCE(a.du_mf, dp.pct_mf2to4 * COALESCE(a.du, r.county_avg_du, 0.0)
        + dp.pct_mf5p * COALESCE(a.du, r.county_avg_du, 0.0), 0.0) AS du_mf,
    CASE
        WHEN a.du IS NOT NULL AND a.du > 0
             AND COALESCE(a.du_detsf_sl, 0) = 0 AND COALESCE(a.du_detsf_ll, 0) = 0
             AND COALESCE(a.du_attsf, 0) = 0 AND COALESCE(a.du_mf2to4, 0) = 0
             AND COALESCE(a.du_mf5p, 0) = 0
        THEN COALESCE(dp.pct_mf2to4 * a.du, 0.0)
        ELSE COALESCE(a.du_mf2to4, dp.pct_mf2to4 * COALESCE(a.du, r.county_avg_du, 0.0), 0.0)
    END AS du_mf2to4,
    CASE
        WHEN a.du IS NOT NULL AND a.du > 0
             AND COALESCE(a.du_detsf_sl, 0) = 0 AND COALESCE(a.du_detsf_ll, 0) = 0
             AND COALESCE(a.du_attsf, 0) = 0 AND COALESCE(a.du_mf2to4, 0) = 0
             AND COALESCE(a.du_mf5p, 0) = 0
        THEN COALESCE(dp.pct_mf5p * a.du, 0.0)
        ELSE COALESCE(a.du_mf5p, dp.pct_mf5p * COALESCE(a.du, r.county_avg_du, 0.0), 0.0)
    END AS du_mf5p,
    a.du_subtype,
    a.is_residential,
    COALESCE(a.residential_building_sqft, 0.0) AS residential_building_sqft,
    COALESCE(a.commercial_building_sqft, 0.0) AS commercial_building_sqft,
    COALESCE(a.industrial_building_sqft, 0.0) AS industrial_building_sqft,
    COALESCE(a.other_building_sqft, 0.0) AS other_building_sqft,
    COALESCE(a.total_footprint_sqft, 0.0) AS total_footprint_sqft,
    COALESCE(a.building_count, 0) AS building_count,
    COALESCE(a.footprint_ratio, 0.0) AS footprint_ratio,
    COALESCE(a.max_levels, 0) AS max_levels,
    COALESCE(a.emp, r.county_avg_emp, 0.0) AS emp,
    a.emp_ret,
    a.emp_retail_services,
    a.emp_restaurant,
    a.emp_accommodation,
    a.emp_arts_entertainment,
    a.emp_other_services,
    a.emp_off,
    a.emp_office_services,
    a.emp_medical_services,
    a.emp_pub,
    a.emp_public_admin,
    a.emp_education,
    a.emp_ind,
    a.emp_manufacturing,
    a.emp_wholesale,
    a.emp_transport_warehousing,
    a.emp_utilities,
    a.emp_construction,
    a.emp_ag,
    a.emp_agriculture,
    a.emp_extraction,
    a.emp_military,
    a.bldg_area_detsf_sl,
    a.bldg_area_detsf_ll,
    a.bldg_area_attsf,
    a.bldg_area_mf,
    a.bldg_area_retail_services,
    a.bldg_area_restaurant,
    a.bldg_area_accommodation,
    a.bldg_area_arts_entertainment,
    a.bldg_area_other_services,
    a.bldg_area_office_services,
    a.bldg_area_public_admin,
    a.bldg_area_education,
    a.bldg_area_medical_services,
    a.bldg_area_transport_warehousing,
    a.bldg_area_wholesale,
    a.residential_irrigated_area,
    a.commercial_irrigated_area,
    a.median_income,
    a.rent_burden_pct,
    a.pct_minority,
    a.pct_college_educated,
    a.cost_burden_pct,
    a.vacancy_rate,
    a.occupied_du
FROM attributes a
LEFT JOIN regional_avg r ON a.county = r.county
LEFT JOIN du_subtype_proportions dp ON a.county = dp.county;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_base_canvas_imputed_geom
  ON @this_model USING GIST (geometry);;
  CREATE INDEX IF NOT EXISTS idx_base_canvas_imputed_parcel_id
  ON @this_model USING btree (parcel_id);;
ANALYZE @this_model;

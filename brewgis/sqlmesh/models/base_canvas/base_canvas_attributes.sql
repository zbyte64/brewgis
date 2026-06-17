MODEL (
  name brewgis.base_canvas.base_canvas_attributes,
  kind VIEW
);

-- Base Canvas Attributes — building areas, land-use classification, irrigation, intersection density.
--
-- Reads from base_canvas_employment, applies calibration parameters from seeds,
-- and computes:
--   1. DU sub-type breakdown (one-hot from du_subtype per methodology Section 5)
--   2. Building areas from Overture building sqft columns
--   3. Land development category from assessor use codes, SACOG text labels
--   4. Area-by-use columns from land_development_category
--   5. Irrigation (residential and commercial irrigated area)
--   6. Intersection density

WITH source_data AS (
    SELECT * FROM brewgis.base_canvas.base_canvas_employment
),

calibration AS (
    SELECT * FROM brewgis.seeds.calibration_parameters
),

assessor_codes AS (
    SELECT use_code, category FROM brewgis.seeds.assessor_use_codes
),

sacog_use AS (
    SELECT land_use_label, category FROM brewgis.seeds.sacog_land_use
),

-- Build per-row calibration join key
with_cal AS (
    SELECT
        s.*,
        COALESCE(NULLIF(s.land_development_category, ''), 'urban') AS lc_key,
        c.sqft_per_du,
        c.sqft_per_emp,
        c.res_irrigation_frac,
        c.com_irrigation_frac,
        c.intersection_density AS calib_int_density
    FROM source_data s
    LEFT JOIN calibration c
        ON COALESCE(NULLIF(s.land_development_category, ''), 'urban') = c.land_development_category
),

-- Demographics with defaults — DU subtype is one-hot from du_subtype (methodology Section 5)
demographics AS (
    SELECT
        *,
        COALESCE(pop_groupquarter, 0.0) AS pop_groupquarter_v,
        -- DU subtype one-hot from du_subtype
        CASE WHEN du_subtype = 'detsf_sl' THEN COALESCE(du, 0.0) ELSE 0.0 END AS du_detsf_sl_v,
        CASE WHEN du_subtype = 'detsf_ll' THEN COALESCE(du, 0.0) ELSE 0.0 END AS du_detsf_ll_v,
        CASE WHEN du_subtype IN ('detsf_sl', 'detsf_ll') THEN COALESCE(du, 0.0) ELSE 0.0 END AS du_detsf_v,
        CASE WHEN du_subtype = 'attsf' THEN COALESCE(du, 0.0) ELSE 0.0 END AS du_attsf_v,
        CASE WHEN du_subtype = 'mf2to4' THEN COALESCE(du, 0.0) ELSE 0.0 END AS du_mf2to4_v,
        CASE WHEN du_subtype = 'mf5p' THEN COALESCE(du, 0.0) ELSE 0.0 END AS du_mf5p_v,
        CASE WHEN du_subtype IN ('mf2to4', 'mf5p') THEN COALESCE(du, 0.0) ELSE 0.0 END AS du_mf_v,
        -- Employment defaults
        COALESCE(emp_ret, emp * 0.2) AS emp_ret_v,
        COALESCE(emp_off, emp * 0.35) AS emp_off_v,
        COALESCE(emp_pub, emp * 0.15) AS emp_pub_v,
        COALESCE(emp_ind, emp * 0.3) AS emp_ind_v,
        COALESCE(emp_retail_services, emp_ret * 0.3) AS emp_retail_services_v,
        COALESCE(emp_restaurant, emp_ret * 0.2) AS emp_restaurant_v,
        COALESCE(emp_accommodation, emp_ret * 0.15) AS emp_accommodation_v,
        COALESCE(emp_arts_entertainment, emp_ret * 0.15) AS emp_arts_entertainment_v,
        COALESCE(emp_other_services, emp_ret * 0.2) AS emp_other_services_v,
        COALESCE(emp_office_services, emp_off * 0.6) AS emp_office_services_v,
        COALESCE(emp_medical_services, emp_off * 0.4) AS emp_medical_services_v,
        COALESCE(emp_public_admin, emp_pub * 0.5) AS emp_public_admin_v,
        COALESCE(emp_education, emp_pub * 0.5) AS emp_education_v,
        COALESCE(emp_manufacturing, emp_ind * 0.3) AS emp_manufacturing_v,
        COALESCE(emp_wholesale, emp_ind * 0.15) AS emp_wholesale_v,
        COALESCE(emp_transport_warehousing, emp_ind * 0.25) AS emp_transport_warehousing_v,
        COALESCE(emp_utilities, emp_ind * 0.1) AS emp_utilities_v,
        COALESCE(emp_construction, emp_ind * 0.2) AS emp_construction_v,
        COALESCE(emp_agriculture, emp_ag * 0.7) AS emp_agriculture_v,
        COALESCE(emp_extraction, emp_ag * 0.3) AS emp_extraction_v
    FROM with_cal
),

-- Building areas from Overture building sqft columns or calibration defaults
building_areas AS (
    SELECT
        *,
        -- Residential building sqft from Overture breakdown
        COALESCE(
            bldg_area_detsf_sl,
            CASE WHEN du_subtype = 'detsf_sl' THEN residential_building_sqft END,
            du_detsf_sl_v * COALESCE(sqft_per_du, 1200.0) * 0.8
        ) AS bldg_area_detsf_sl_v,
        COALESCE(
            bldg_area_detsf_ll,
            CASE WHEN du_subtype = 'detsf_ll' THEN residential_building_sqft END,
            du_detsf_ll_v * COALESCE(sqft_per_du, 1200.0) * 1.2
        ) AS bldg_area_detsf_ll_v,
        COALESCE(
            bldg_area_attsf,
            CASE WHEN du_subtype = 'attsf' THEN residential_building_sqft END,
            du_attsf_v * COALESCE(sqft_per_du, 1200.0) * 0.9
        ) AS bldg_area_attsf_v,
        COALESCE(
            bldg_area_mf,
            CASE WHEN du_subtype IN ('mf2to4', 'mf5p') THEN residential_building_sqft END,
            du_mf_v * COALESCE(sqft_per_du, 1200.0) * 0.7
        ) AS bldg_area_mf_v,
        -- Employment building areas from Overture commercial/industrial sqft columns
        COALESCE(
            bldg_area_retail_services,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_retail_services_v, 0) / NULLIF(COALESCE(emp_ret_v, 0), 0)
            END,
            emp_retail_services_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_retail_services_v,
        COALESCE(
            bldg_area_restaurant,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_restaurant_v, 0) / NULLIF(COALESCE(emp_ret_v, 0), 0)
            END,
            emp_restaurant_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_restaurant_v,
        COALESCE(
            bldg_area_accommodation,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_accommodation_v, 0) / NULLIF(COALESCE(emp_ret_v, 0), 0)
            END,
            emp_accommodation_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_accommodation_v,
        COALESCE(
            bldg_area_arts_entertainment,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_arts_entertainment_v, 0) / NULLIF(COALESCE(emp_ret_v, 0), 0)
            END,
            emp_arts_entertainment_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_arts_entertainment_v,
        COALESCE(
            bldg_area_other_services,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_other_services_v, 0) / NULLIF(COALESCE(emp_ret_v, 0), 0)
            END,
            emp_other_services_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_other_services_v,
        COALESCE(
            bldg_area_office_services,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_office_services_v, 0) / NULLIF(COALESCE(emp_off_v, 0), 0)
            END,
            emp_office_services_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_office_services_v,
        COALESCE(
            bldg_area_public_admin,
            CASE WHEN other_building_sqft > 0
                THEN other_building_sqft * COALESCE(emp_public_admin_v, 0) / NULLIF(COALESCE(emp_pub_v, 0), 0)
            END,
            emp_public_admin_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_public_admin_v,
        COALESCE(
            bldg_area_education,
            CASE WHEN other_building_sqft > 0
                THEN other_building_sqft * COALESCE(emp_education_v, 0) / NULLIF(COALESCE(emp_pub_v, 0), 0)
            END,
            emp_education_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_education_v,
        COALESCE(
            bldg_area_medical_services,
            CASE WHEN commercial_building_sqft > 0
                THEN commercial_building_sqft * COALESCE(emp_medical_services_v, 0) / NULLIF(COALESCE(emp_off_v, 0), 0)
            END,
            emp_medical_services_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_medical_services_v,
        COALESCE(
            bldg_area_transport_warehousing,
            CASE WHEN industrial_building_sqft > 0
                THEN industrial_building_sqft * COALESCE(emp_transport_warehousing_v, 0) / NULLIF(COALESCE(emp_ind_v, 0), 0)
            END,
            emp_transport_warehousing_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_transport_warehousing_v,
        COALESCE(
            bldg_area_wholesale,
            CASE WHEN industrial_building_sqft > 0
                THEN industrial_building_sqft * COALESCE(emp_wholesale_v, 0) / NULLIF(COALESCE(emp_ind_v, 0), 0)
            END,
            emp_wholesale_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_wholesale_v
    FROM demographics
),

-- Overture land use fallback classification
overture_lu AS (
    SELECT parcel_id, overture_category
    FROM brewgis.assessor.overture_land_use_parcel
),

-- Land use classification derived from assessor codes, SACOG labels,
-- or Overture land use as final fallback before defaulting to 'urban'
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

-- Area by use from land_development_category
area_by_use AS (
    SELECT
        *,
        lnd_v AS lnd_category,
        bf_v AS bf_key,
        CASE
            WHEN du_subtype IS NOT NULL THEN COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0)
            WHEN lnd_v IN ('industrial', 'agricultural', 'undeveloped') THEN 0
            WHEN lnd_v IN ('urban', 'mixed_use')
                 AND COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                     + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0) > 0
                 AND (COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                      + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0))
                     / NULLIF(COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0) * 43560, 0) >= 0.02
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
            WHEN du_subtype IS NOT NULL THEN 0
            WHEN COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                 + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0) > 0
                 AND (COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                      + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0))
                     / NULLIF(COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0) * 43560, 0) >= 0.02
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
            WHEN du_subtype IS NOT NULL THEN 0
            WHEN COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                 + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0) > 0
                 AND (COALESCE(residential_building_sqft, 0) + COALESCE(commercial_building_sqft, 0)
                      + COALESCE(industrial_building_sqft, 0) + COALESCE(other_building_sqft, 0))
                     / NULLIF(COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0) * 43560, 0) >= 0.02
                 THEN 0
            WHEN lnd_v IN ('urban', 'mixed_use') THEN COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0)
            WHEN lnd_v = 'undeveloped' THEN COALESCE(area_parcel_acres, area_gross_acres, area_gross, 0)
            ELSE area_parcel_no_use
        END AS area_parcel_no_use_v
    FROM classified
),

-- NLCD impervious surface data and tree canopy cover fraction
nlcd_data AS (
    SELECT
        n.parcel_id,
        n.impervious_fraction,
        tc.tree_canopy_fraction
    FROM brewgis.nlcd.nlcd_parcel_stats n
    LEFT JOIN brewgis.nlcd.nlcd_tree_canopy_parcel_stats tc
        ON n.parcel_id = tc.parcel_id
),

-- Irrigation — uses NLCD impervious fraction when available, else calibration defaults
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

-- Intersection density — from Overture, else calibration or default
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

-- Final output
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
    ROUND((du * (1.0 - COALESCE(vacancy_rate, 0.0)))::numeric, 2) AS occupied_du
FROM with_intersection;

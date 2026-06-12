MODEL (
  name brewgis.base_canvas.base_canvas_attributes,
  kind VIEW
);

-- Base Canvas Attributes — building areas, land-use classification, irrigation, intersection density.
--
-- Reads from base_canvas_employment, applies calibration parameters from seeds,
-- and computes:
--   1. Demographic sub-type defaults (pop_groupquarter, du subtypes)
--   2. Building areas from dwelling units (using calibration sqft_per_du)
--   3. Building areas from employment (using calibration sqft_per_emp)
--   4. Land development category from assessor use codes, SACOG text labels
--   5. Area-by-use columns from land_development_category
--   6. Irrigation (residential and commercial irrigated area)
--   7. Intersection density from calibration defaults
--
-- NLCD and dasymetric weight integration disabled (default).
-- OSM intersection density is controlled by the ``osm_intersection_table`` variable.

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

-- Demographics with defaults
demographics AS (
    SELECT
        *,
        COALESCE(pop_groupquarter, 0.0) AS pop_groupquarter_v,
        COALESCE(du_detsf,
            CASE WHEN du_subtype IN ('detsf_sl', 'detsf_ll') THEN du END,
            du * 0.4
        ) AS du_detsf_v,
        COALESCE(du_detsf_sl,
            CASE WHEN du_subtype = 'detsf_sl' THEN du END,
            du * 0.4 * 0.5
        ) AS du_detsf_sl_v,
        COALESCE(du_detsf_ll,
            CASE WHEN du_subtype = 'detsf_ll' THEN du END,
            du * 0.4 * 0.5
        ) AS du_detsf_ll_v,
        COALESCE(du_attsf,
            CASE WHEN du_subtype = 'attsf' THEN du END,
            du * 0.2
        ) AS du_attsf_v,
        COALESCE(du_mf,
            CASE WHEN du_subtype IN ('mf2to4', 'mf5p') THEN du END,
            du * 0.4
        ) AS du_mf_v,
        COALESCE(du_mf2to4,
            CASE WHEN du_subtype = 'mf2to4' THEN du END,
            du * 0.4 * 0.3
        ) AS du_mf2to4_v,
        COALESCE(du_mf5p,
            CASE WHEN du_subtype = 'mf5p' THEN du END,
            du * 0.4 * 0.7
        ) AS du_mf5p_v,
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

-- Building areas from DU * calibration.sqft_per_du * factor
-- Without dasymetric weights, assessor_res_sqft/assessor_emp_sqft are NULL
building_areas AS (
    SELECT
        *,
        COALESCE(
            bldg_area_detsf_sl,
            CASE WHEN du_subtype = 'detsf_sl' THEN footprint_living_sqft END,
            du_detsf_sl_v * COALESCE(sqft_per_du, 1200.0) * 0.8
        ) AS bldg_area_detsf_sl_v,
        COALESCE(
            bldg_area_detsf_ll,
            CASE WHEN du_subtype = 'detsf_ll' THEN footprint_living_sqft END,
            du_detsf_ll_v * COALESCE(sqft_per_du, 1200.0) * 1.2
        ) AS bldg_area_detsf_ll_v,
        COALESCE(
            bldg_area_attsf,
            CASE WHEN du_subtype = 'attsf' THEN footprint_living_sqft END,
            du_attsf_v * COALESCE(sqft_per_du, 1200.0) * 0.9
        ) AS bldg_area_attsf_v,
        COALESCE(
            bldg_area_mf,
            CASE WHEN du_subtype IN ('mf2to4', 'mf5p') THEN footprint_building_sqft END,
            du_mf_v * COALESCE(sqft_per_du, 1200.0) * 0.7
        ) AS bldg_area_mf_v,
        -- Employment building areas (Tier 3 fallback only):
        -- We cannot split total building sqft by 15 employment sub-types,
        -- so these remain DU/emp * sqft_per_emp imputation.
        -- Future: Overture `class` column (residential/commercial/industrial)
        -- could distinguish residential vs non-residential footprints,
        -- but not NAICS-level detail required here.
        COALESCE(
            bldg_area_retail_services,
            emp_retail_services_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_retail_services_v,
        COALESCE(
            bldg_area_restaurant,
            emp_restaurant_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_restaurant_v,
        COALESCE(
            bldg_area_accommodation,
            emp_accommodation_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_accommodation_v,
        COALESCE(
            bldg_area_arts_entertainment,
            emp_arts_entertainment_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_arts_entertainment_v,
        COALESCE(
            bldg_area_other_services,
            emp_other_services_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_other_services_v,
        COALESCE(
            bldg_area_office_services,
            emp_office_services_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_office_services_v,
        COALESCE(
            bldg_area_public_admin,
            emp_public_admin_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_public_admin_v,
        COALESCE(
            bldg_area_education,
            emp_education_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_education_v,
        COALESCE(
            bldg_area_medical_services,
            emp_medical_services_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_medical_services_v,
        COALESCE(
            bldg_area_transport_warehousing,
            emp_transport_warehousing_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_transport_warehousing_v,
        COALESCE(
            bldg_area_wholesale,
            emp_wholesale_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_wholesale_v
    FROM demographics
),

-- Land use classification derived from assessor codes or SACOG labels
classified AS (
    SELECT
        b.*,
        COALESCE(
            NULLIF(b.land_development_category, ''),
            ac.category,
            su.category,
            'urban'
        ) AS lnd_v,
        COALESCE(NULLIF(b.built_form_key, ''), 'mixed_use') AS bf_v
    FROM building_areas b
    LEFT JOIN assessor_codes ac
        ON LEFT(COALESCE(b.assessor_use_code, ''), 2) = ac.use_code::text
    LEFT JOIN sacog_use su
        ON TRIM(COALESCE(b.land_use, '')) = su.land_use_label
),

-- Area by use from land_development_category
area_by_use AS (
    SELECT
        *,
        lnd_v AS lnd_category,
        bf_v AS bf_key,
        CASE
            -- Parcels with DU subtypes → full residential (known use from assessor)
            WHEN du_subtype IS NOT NULL THEN COALESCE(area_parcel, area_gross, 0)
            -- Industrial/Agra/Under → 0 res (no residential use)
            WHEN lnd_v IN ('industrial', 'agricultural', 'undeveloped') THEN 0
            -- Urban/mixed without du_subtype, with significant building coverage → proportional split
            WHEN lnd_v IN ('urban', 'mixed_use')
                 AND COALESCE(residential_building_sqft, 0) + COALESCE(non_residential_building_sqft, 0) > 0
                 AND (COALESCE(residential_building_sqft, 0) + COALESCE(non_residential_building_sqft, 0))
                     / NULLIF(COALESCE(area_parcel, area_gross, 0) * 43560, 0) >= 0.02
                 THEN COALESCE(area_parcel, area_gross, 0)
                      * COALESCE(residential_building_sqft, 0)
                        / NULLIF(COALESCE(residential_building_sqft, 0) + COALESCE(non_residential_building_sqft, 0), 0)
            -- Urban/mixed without significant building data → no_use (DON'T assume res)
            WHEN lnd_v IN ('urban', 'mixed_use') THEN 0
            -- Explicit res → res (from source parcel data)
            ELSE area_parcel_res
        END AS area_parcel_res_v,
        CASE WHEN lnd_v = 'agricultural'
            THEN COALESCE(area_parcel, area_gross, 0) ELSE area_parcel_emp_ag END AS area_parcel_emp_ag_v,
        CASE
            -- Parcels with du_subtype → residential use, no emp allocation
            WHEN du_subtype IS NOT NULL THEN 0
            -- No du_subtype, with significant building coverage → proportional split (non-residential share)
            WHEN COALESCE(residential_building_sqft, 0) + COALESCE(non_residential_building_sqft, 0) > 0
                 AND (COALESCE(residential_building_sqft, 0) + COALESCE(non_residential_building_sqft, 0))
                     / NULLIF(COALESCE(area_parcel, area_gross, 0) * 43560, 0) >= 0.02
                 THEN COALESCE(area_parcel, area_gross, 0)
                      * COALESCE(non_residential_building_sqft, 0)
                        / NULLIF(COALESCE(residential_building_sqft, 0) + COALESCE(non_residential_building_sqft, 0), 0)
            -- Industrial → full area to emp
            WHEN lnd_v = 'industrial' THEN COALESCE(area_parcel, area_gross, 0)
            -- Urban/mixed without building data → 0 emp (no employment evidence)
            WHEN lnd_v IN ('urban', 'mixed_use') THEN 0
            -- Agricultural/Undeveloped → 0 emp
            WHEN lnd_v IN ('agricultural', 'undeveloped') THEN 0
            -- Explicit emp → emp (from source parcel data)
            ELSE COALESCE(area_parcel_emp, 0)
        END AS area_parcel_emp_v,
        CASE WHEN lnd_v = 'mixed_use'
            THEN COALESCE(area_parcel, area_gross, 0) ELSE area_parcel_mixed_use END AS area_parcel_mixed_use_v,
        CASE
            -- Known use (du_subtype or significant building coverage) → none to no_use
            WHEN du_subtype IS NOT NULL THEN 0
            WHEN COALESCE(residential_building_sqft, 0) + COALESCE(non_residential_building_sqft, 0) > 0
                 AND (COALESCE(residential_building_sqft, 0) + COALESCE(non_residential_building_sqft, 0))
                     / NULLIF(COALESCE(area_parcel, area_gross, 0) * 43560, 0) >= 0.02
                 THEN 0
            -- Urban/mixed without any building data → full area to no_use
            WHEN lnd_v IN ('urban', 'mixed_use') THEN COALESCE(area_parcel, area_gross, 0)
            -- Undeveloped → full area to no_use
            WHEN lnd_v = 'undeveloped' THEN COALESCE(area_parcel, area_gross, 0)
            -- Explicit no_use → no_use (from source parcel data)
            ELSE area_parcel_no_use
        END AS area_parcel_no_use_v
    FROM classified
),

-- NLCD impervious surface data (zonal stats on SACOG parcels)
nlcd_data AS (
    SELECT parcel_id, impervious_fraction
    FROM brewgis.nlcd.nlcd_parcel_stats
),

-- Irrigation — uses NLCD impervious fraction when available, else calibration defaults
irrigation AS (
    SELECT
        abu.*,
        nlcd.impervious_fraction,
        COALESCE(abu.residential_irrigated_area,
            COALESCE(abu.area_parcel_res_v, abu.area_gross, 0)
                * COALESCE(NULLIF(nlcd.impervious_fraction, 0), NULLIF(abu.dasym_impervious_fraction, 0), abu.res_irrigation_frac, 0.064)
        ) AS residential_irrigated_area_v,
        COALESCE(abu.commercial_irrigated_area,
            COALESCE(abu.area_parcel_emp_v, abu.area_gross, 0)
                * COALESCE(NULLIF(nlcd.impervious_fraction, 0), NULLIF(abu.dasym_impervious_fraction, 0), abu.com_irrigation_frac, 0.035)
        ) AS commercial_irrigated_area_v
    FROM area_by_use abu
    LEFT JOIN nlcd_data nlcd ON abu.parcel_id = nlcd.parcel_id
),

-- Intersection density — optionally from OSM, else calibration or default
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
    area_parcel,
    area_dev_condition,
    area_row,
    area_parcel_res_v AS area_parcel_res,
    area_parcel_emp_ag_v AS area_parcel_emp_ag,
    area_parcel_emp_v AS area_parcel_emp,
    area_parcel_mixed_use_v AS area_parcel_mixed_use,
    area_parcel_no_use_v AS area_parcel_no_use,
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
    cost_burden_pct
FROM with_intersection

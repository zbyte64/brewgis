{#
    Base Canvas Attributes — building areas, land-use classification, irrigation, intersection density.

    Reads from ``base_canvas_employment``, applies calibration parameters
    from seeds, and computes:

      1. Demographic sub-type defaults (pop_groupquarter, du subtypes)
      2. Building areas from dwelling units (using calibration sqft_per_du)
      3. Building areas from employment (using calibration sqft_per_emp)
      4. Land development category from assessor use codes, SACOG text labels, or NLCD (optional)
      5. Area-by-use columns from land_development_category
      6. Irrigation (residential and commercial irrigated area) — uses NLCD impervious fraction when available
      7. Intersection density — uses OSM when available, falls back to calibration or default


    Calibration seeds:
      - calibration_parameters: per-category (sqft_per_du, sqft_per_emp, res_irrigation_frac, com_irrigation_frac, intersection_density)
      - assessor_use_codes: 2-digit assessor code -> category
      - sacog_land_use: text land-use label -> category
      - nlcd_parcel_table var: NLCD zonal stats (land_development_category, impervious_fraction)
      - osm_intersection_table var: OSM intersection density


    Materialized as: view
#}
{{ config(materialized=var('base_canvas_materialized', 'view')) }}
{% set nlcd_table = var('nlcd_parcel_table', '') %}
{% set osm_table = var('osm_intersection_table', '') %}
{% set dasym_table = var('dasymetric_weights_table', '') %}


WITH source_data AS (
    SELECT * FROM {{ ref('base_canvas_employment') }}
),

calibration AS (
    SELECT * FROM {{ ref('calibration_parameters') }}
),

assessor_codes AS (
    SELECT use_code, category FROM {{ ref('assessor_use_codes') }}
),

sacog_use AS (
    SELECT land_use_label, category FROM {{ ref('sacog_land_use') }}
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
        COALESCE(du_detsf, du * 0.4) AS du_detsf_v,
        COALESCE(du_detsf_sl, du * 0.4 * 0.5) AS du_detsf_sl_v,
        COALESCE(du_detsf_ll, du * 0.4 * 0.5) AS du_detsf_ll_v,
        COALESCE(du_attsf, du * 0.2) AS du_attsf_v,
        COALESCE(du_mf, du * 0.4) AS du_mf_v,
        COALESCE(du_mf2to4, du * 0.4 * 0.3) AS du_mf2to4_v,
        COALESCE(du_mf5p, du * 0.4 * 0.7) AS du_mf5p_v,
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


-- Assessor dasymetric building data (optional — from parcel_dasymetric_weights)
-- Provides actual/estimated living and building sqft per parcel for building area refinement.
{% if dasym_table %}
dasym_source AS (
    SELECT
        d.*,
        COALESCE(dw.actual_living_sqft, dw.estimated_living_sqft) AS assessor_res_sqft,
        COALESCE(dw.actual_building_sqft, dw.estimated_building_sqft) AS assessor_emp_sqft
    FROM demographics d
    LEFT JOIN {{ dasym_table }} dw ON d.parcel_id::text = dw.parcel_id::text
    LEFT JOIN {{ dasym_table }} dw ON d.parcel_id = dw.parcel_id
),
{% else %}
dasym_source AS (
    SELECT *,
        NULL::double precision AS assessor_res_sqft,
        NULL::double precision AS assessor_emp_sqft
    FROM demographics
),
{% endif %}

-- Building areas from DU * calibration.sqft_per_du * factor
building_areas AS (
    SELECT
        *,
        COALESCE(
            bldg_area_detsf_sl,
            CASE WHEN assessor_res_sqft IS NOT NULL AND du > 0
                THEN ROUND((assessor_res_sqft * du_detsf_sl_v / du)::numeric, 1)
                ELSE NULL
            END,
            du_detsf_sl_v * COALESCE(sqft_per_du, 1200.0) * 0.8
        ) AS bldg_area_detsf_sl_v,
        COALESCE(
            bldg_area_detsf_ll,
            CASE WHEN assessor_res_sqft IS NOT NULL AND du > 0
                THEN ROUND((assessor_res_sqft * du_detsf_ll_v / du)::numeric, 1)
                ELSE NULL
            END,
            du_detsf_ll_v * COALESCE(sqft_per_du, 1200.0) * 1.2
        ) AS bldg_area_detsf_ll_v,
        COALESCE(
            bldg_area_attsf,
            CASE WHEN assessor_res_sqft IS NOT NULL AND du > 0
                THEN ROUND((assessor_res_sqft * du_attsf_v / du)::numeric, 1)
                ELSE NULL
            END,
            du_attsf_v * COALESCE(sqft_per_du, 1200.0) * 0.9
        ) AS bldg_area_attsf_v,
        COALESCE(
            bldg_area_mf,
            CASE WHEN assessor_res_sqft IS NOT NULL AND du > 0
                THEN ROUND((assessor_res_sqft * du_mf_v / du)::numeric, 1)
                ELSE NULL
            END,
            du_mf_v * COALESCE(sqft_per_du, 1200.0) * 0.7
        ) AS bldg_area_mf_v,
        COALESCE(
            bldg_area_retail_services,
            CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
                THEN ROUND((assessor_emp_sqft * emp_retail_services_v / emp)::numeric, 1)
                ELSE NULL
            END,
            emp_retail_services_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_retail_services_v,
        COALESCE(
            bldg_area_restaurant,
            CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
                THEN ROUND((assessor_emp_sqft * emp_restaurant_v / emp)::numeric, 1)
                ELSE NULL
            END,
            emp_restaurant_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_restaurant_v,
        COALESCE(
            bldg_area_accommodation,
            CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
                THEN ROUND((assessor_emp_sqft * emp_accommodation_v / emp)::numeric, 1)
                ELSE NULL
            END,
            emp_accommodation_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_accommodation_v,
        COALESCE(
            bldg_area_arts_entertainment,
            CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
                THEN ROUND((assessor_emp_sqft * emp_arts_entertainment_v / emp)::numeric, 1)
                ELSE NULL
            END,
            emp_arts_entertainment_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_arts_entertainment_v,
        COALESCE(
            bldg_area_other_services,
            CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
                THEN ROUND((assessor_emp_sqft * emp_other_services_v / emp)::numeric, 1)
                ELSE NULL
            END,
            emp_other_services_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_other_services_v,
        COALESCE(
            bldg_area_office_services,
            CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
                THEN ROUND((assessor_emp_sqft * emp_office_services_v / emp)::numeric, 1)
                ELSE NULL
            END,
            emp_office_services_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_office_services_v,
        COALESCE(
            bldg_area_public_admin,
            CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
                THEN ROUND((assessor_emp_sqft * emp_public_admin_v / emp)::numeric, 1)
                ELSE NULL
            END,
            emp_public_admin_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_public_admin_v,
        COALESCE(
            bldg_area_education,
            CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
                THEN ROUND((assessor_emp_sqft * emp_education_v / emp)::numeric, 1)
                ELSE NULL
            END,
            emp_education_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_education_v,
        COALESCE(
            bldg_area_medical_services,
            CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
                THEN ROUND((assessor_emp_sqft * emp_medical_services_v / emp)::numeric, 1)
                ELSE NULL
            END,
            emp_medical_services_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_medical_services_v,
        COALESCE(
            bldg_area_transport_warehousing,
            CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
                THEN ROUND((assessor_emp_sqft * emp_transport_warehousing_v / emp)::numeric, 1)
                ELSE NULL
            END,
            emp_transport_warehousing_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_transport_warehousing_v,
        COALESCE(
            bldg_area_wholesale,
            CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
                THEN ROUND((assessor_emp_sqft * emp_wholesale_v / emp)::numeric, 1)
                ELSE NULL
            END,
            emp_wholesale_v * COALESCE(sqft_per_emp, 300.0)
        ) AS bldg_area_wholesale_v
    FROM dasym_source
),

-- Land use classification derived from assessor codes or SACOG text
classified AS (
    SELECT
        b.*,
        COALESCE(
            NULLIF(b.land_development_category, ''),
            ac.category,
            su.category,
            {% if nlcd_table %}nlcd.land_development_category,{% endif %}
            'urban'
        ) AS lnd_v,
        COALESCE(NULLIF(b.built_form_key, ''), 'mixed_use') AS bf_v
    {% if nlcd_table %},
        nlcd.impervious_fraction
    {% endif %}
    FROM building_areas b

    LEFT JOIN assessor_codes ac
        ON LEFT(COALESCE(b.assessor_use_code, ''), 2) = ac.use_code::text
    LEFT JOIN sacog_use su
        ON TRIM(COALESCE(b.land_use, '')) = su.land_use_label
    {% if nlcd_table %}LEFT JOIN {{ nlcd_table }} nlcd
        ON b.parcel_id = nlcd.parcel_id
    {% endif %}
),


-- Area by use from land_development_category
area_by_use AS (
    SELECT
        *,
        lnd_v AS lnd_category,
        bf_v AS bf_key,
        CASE WHEN lnd_v = 'urban'
            THEN COALESCE(area_parcel, area_gross, 0) ELSE area_parcel_res END AS area_parcel_res_v,
        CASE WHEN lnd_v = 'agricultural'
            THEN COALESCE(area_parcel, area_gross, 0) ELSE area_parcel_emp_ag END AS area_parcel_emp_ag_v,
        CASE WHEN lnd_v = 'industrial'
            THEN COALESCE(area_parcel, area_gross, 0) ELSE area_parcel_emp END AS area_parcel_emp_v,
        CASE WHEN lnd_v = 'mixed_use'
            THEN COALESCE(area_parcel, area_gross, 0) ELSE area_parcel_mixed_use END AS area_parcel_mixed_use_v,
        CASE WHEN lnd_v = 'undeveloped'
            THEN COALESCE(area_parcel, area_gross, 0) ELSE area_parcel_no_use END AS area_parcel_no_use_v
    FROM classified
),

-- Irrigation
irrigation AS (
    SELECT
        *,
        COALESCE(residential_irrigated_area,
            {% if nlcd_table %}
            COALESCE(area_parcel_res_v, area_gross, 0) * (1 - COALESCE(impervious_fraction, 0)) * COALESCE(res_irrigation_frac, 0.25)
            {% else %}
            COALESCE(area_parcel_res_v, area_gross, 0) * COALESCE(res_irrigation_frac, 0.25)
            {% endif %}
        ) AS residential_irrigated_area_v,
        COALESCE(commercial_irrigated_area,
            {% if nlcd_table %}
            COALESCE(area_parcel_emp_v, area_gross, 0) * (1 - COALESCE(impervious_fraction, 0)) * COALESCE(com_irrigation_frac, 0.035)
            {% else %}
            COALESCE(area_parcel_emp_v, area_gross, 0) * COALESCE(com_irrigation_frac, 0.035)
            {% endif %}
        ) AS commercial_irrigated_area_v
    FROM area_by_use
),

-- Intersection density
int_density AS (
    SELECT
        i.*
        {% if osm_table %},
        osm.intersection_density AS osm_intersection_density
        {% endif %}
    FROM irrigation i
    {% if osm_table %}LEFT JOIN {{ osm_table }} osm
        ON i.parcel_id = osm.parcel_id
    {% endif %}
),
with_intersection AS (
    SELECT
        *,
        ROUND(COALESCE(
            {% if osm_table %}NULLIF(osm_intersection_density, 0),{% endif %}
            NULLIF(intersection_density, 0),
            COALESCE(calib_int_density, 12.5)
        )::numeric, 2) AS int_dens_v
    FROM int_density
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
    -- Demographics
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
    -- Employment
    COALESCE(emp, 0.0) AS emp,
    emp_ret_v AS emp_ret,
    emp_off_v AS emp_off,
    emp_pub_v AS emp_pub,
    emp_ind_v AS emp_ind,
    emp_ag AS emp_ag,
    emp_military AS emp_military,
    -- Employment sub-sectors
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
    -- Building areas
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
    -- Irrigation
    residential_irrigated_area_v AS residential_irrigated_area,
    commercial_irrigated_area_v AS commercial_irrigated_area,
    -- Equity columns
    median_income,
    rent_burden_pct,
    pct_minority,
    pct_college_educated,
    cost_burden_pct
FROM with_intersection

{#
    Base Canvas Imputed — three-tier imputation cascade.

    Tier 1: Direct value from ``base_canvas_attributes`` (preserves existing values)
    Tier 2: County average for remaining NULLs (window function)
    Tier 3: National default constant as final fallback

    Reads from ``base_canvas_attributes``.

    Materialized as: view
#}
{{ config(materialized=var('base_canvas_materialized', 'view')) }}

WITH attributes AS (
    SELECT * FROM {{ ref('base_canvas_attributes') }}
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
)

SELECT
    a.parcel_id,
    a.geometry,
    a.county,
    a.land_development_category,
    a.built_form_key,
    -- Intersection density: COALESCE(a_value, regional_avg, national_default)
    ROUND(COALESCE(
        NULLIF(a.intersection_density, 0),
        r.county_avg_int_density,
        12.5
    )::numeric, 2) AS intersection_density,
    a.area_gross,
    a.area_parcel,
    a.area_dev_condition,
    a.area_row,
    -- Demographics: COALESCE(a_value, regional_avg, 0.0)
    COALESCE(NULLIF(a.pop, 0), r.county_avg_pop, 0.0) AS pop,
    COALESCE(NULLIF(a.pop_groupquarter, 0), 0.0) AS pop_groupquarter,
    COALESCE(NULLIF(a.hh, 0), r.county_avg_hh, 0.0) AS hh,
    COALESCE(NULLIF(a.du, 0), r.county_avg_du, 0.0) AS du,
    a.du_detsf,
    a.du_detsf_sl,
    a.du_detsf_ll,
    a.du_attsf,
    a.du_mf,
    a.du_mf2to4,
    a.du_mf5p,
    COALESCE(NULLIF(a.emp, 0), r.county_avg_emp, 0.0) AS emp,
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
    a.cost_burden_pct
FROM attributes a
LEFT JOIN regional_avg r ON a.county = r.county

{#
    Base Canvas Attributes — second ETL step (SQL)

    Reads from ``base_canvas_geometry``, fills computed defaults for
    demographics, employment, building areas, land-use classification,
    irrigation, and intersection density.

    Follows ``populate_base_canvas.py`` steps 4-9.
#}
{{ config(materialized='view') }}

WITH geometry_data AS (
    SELECT * FROM {{ ref('base_canvas_geometry') }}
),

demographics AS (
    SELECT
        *,
        COALESCE(pop, 0.0) AS pop_v,
        COALESCE(pop * 0.0, 0.0) AS pop_groupquarter_v,
        COALESCE(hh, 0.0) AS hh_v,
        COALESCE(du, 0.0) AS du_v,
        COALESCE(du * 0.4, 0.0) AS du_detsf_v,
        COALESCE(du * 0.4 * 0.5, 0.0) AS du_detsf_sl_v,
        COALESCE(du * 0.4 * 0.5, 0.0) AS du_detsf_ll_v,
        COALESCE(du * 0.2, 0.0) AS du_attsf_v,
        COALESCE(du * 0.4, 0.0) AS du_mf_v,
        COALESCE(du * 0.4 * 0.3, 0.0) AS du_mf2to4_v,
        COALESCE(du * 0.4 * 0.7, 0.0) AS du_mf5p_v,
        COALESCE(emp, 0.0) AS emp_v,
        COALESCE(emp * 0.2, 0.0) AS emp_ret_v,
        COALESCE(emp * 0.35, 0.0) AS emp_off_v,
        COALESCE(emp * 0.15, 0.0) AS emp_pub_v,
        COALESCE(emp * 0.3, 0.0) AS emp_ind_v
    FROM geometry_data
),

building_areas AS (
    SELECT
        *,
        COALESCE(du_detsf_sl_v * 1200.0 * 0.8, 0.0) AS bldg_area_detsf_sl_v,
        COALESCE(du_detsf_ll_v * 1200.0 * 1.2, 0.0) AS bldg_area_detsf_ll_v,
        COALESCE(du_attsf_v * 1200.0 * 0.9, 0.0) AS bldg_area_attsf_v,
        COALESCE(du_mf_v * 1200.0 * 0.7, 0.0) AS bldg_area_mf_v,
        COALESCE(emp_ret_v * 300.0, 0.0) AS bldg_area_retail_services_v,
        COALESCE(emp_off_v * 300.0, 0.0) AS bldg_area_office_services_v,
        COALESCE(emp_pub_v * 300.0, 0.0) AS bldg_area_public_admin_v,
        COALESCE(emp_ind_v * 300.0, 0.0) AS bldg_area_transport_warehousing_v
    FROM demographics
),

defaults AS (
    SELECT
        *,
        COALESCE(NULLIF(land_development_category, ''), 'urban') AS lnd_v,
        COALESCE(built_form_key, 'mixed_use') AS bf_v,
        ROUND(COALESCE(intersection_density, 12.5)::numeric, 2) AS int_dens_v,
        COALESCE(area_gross * 0.1, 0.0) AS res_irr_v,
        COALESCE(area_gross * 0.05, 0.0) AS com_irr_v
    FROM building_areas
)

SELECT
    parcel_id,
    geometry,
    county,
    lnd_v AS land_development_category,
    bf_v AS built_form_key,
    int_dens_v AS intersection_density,
    area_gross,
    area_parcel,
    area_dev_condition,
    area_row,
    -- Demographics
    pop_v AS pop,
    pop_groupquarter_v AS pop_groupquarter,
    hh_v AS hh,
    du_v AS du,
    du_detsf_v AS du_detsf,
    du_detsf_sl_v AS du_detsf_sl,
    du_detsf_ll_v AS du_detsf_ll,
    du_attsf_v AS du_attsf,
    du_mf_v AS du_mf,
    du_mf2to4_v AS du_mf2to4,
    du_mf5p_v AS du_mf5p,
    -- Employment
    emp_v AS emp,
    emp_ret_v AS emp_ret,
    emp_off_v AS emp_off,
    emp_pub_v AS emp_pub,
    emp_ind_v AS emp_ind,
    -- Building areas
    bldg_area_detsf_sl_v AS bldg_area_detsf_sl,
    bldg_area_detsf_ll_v AS bldg_area_detsf_ll,
    bldg_area_attsf_v AS bldg_area_attsf,
    bldg_area_mf_v AS bldg_area_mf,
    bldg_area_retail_services_v AS bldg_area_retail_services,
    bldg_area_office_services_v AS bldg_area_office_services,
    bldg_area_public_admin_v AS bldg_area_public_admin,
    bldg_area_transport_warehousing_v AS bldg_area_transport_warehousing,
    -- Irrigation & intersection density
    res_irr_v AS residential_irrigated_area,
    com_irr_v AS commercial_irrigated_area
FROM defaults

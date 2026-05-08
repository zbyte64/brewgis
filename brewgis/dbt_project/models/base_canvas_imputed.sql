{#
    Base Canvas Imputed — third ETL step (SQL)

    Three-tier imputation cascade:
      Tier 1: Direct observation (NA for seed-based data)
      Tier 2: Regional (county) average for remaining NULLs
      Tier 3: National default constant as final fallback

    Reads from ``base_canvas_attributes`` which already has per-column
    defaults filled.  This model adds regional-averaging logic via
    window functions for columns that may still be NULL.

    Materialized as: view
#}
{{ config(materialized='view') }}

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
),

-- Apply Tier 2 (regional avg) then Tier 3 (national default)
imputed AS (
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
        a.emp_off,
        a.emp_pub,
        a.emp_ind,
        a.bldg_area_detsf_sl,
        a.bldg_area_detsf_ll,
        a.bldg_area_attsf,
        a.bldg_area_mf,
        a.bldg_area_retail_services,
        a.bldg_area_office_services,
        a.bldg_area_public_admin,
        a.bldg_area_transport_warehousing,
        a.residential_irrigated_area,
        a.commercial_irrigated_area
    FROM attributes a
    LEFT JOIN regional_avg r ON a.county = r.county
)

SELECT * FROM imputed

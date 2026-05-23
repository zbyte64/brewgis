{#
    Base Canvas Reconciled — recompute aggregate columns from sub-columns.

    Reads from ``base_canvas_imputed`` and ensures that aggregate columns
    equal the sum of their constituent sub-columns.

    Reconciliation rules (from Python _reconcile_aggregates):
      du_detsf = du_detsf_sl + du_detsf_ll
      du_mf = du_mf2to4 + du_mf5p
      du = du_detsf + du_attsf + du_mf
      emp_ret = emp_retail_services + emp_restaurant + emp_accommodation
                + emp_arts_entertainment + emp_other_services
      emp_off = emp_office_services + emp_medical_services
      emp_pub = emp_public_admin + emp_education
      emp_ind = emp_manufacturing + emp_wholesale + emp_transport_warehousing
                + emp_utilities + emp_construction
      emp_ag = emp_agriculture + emp_extraction
      emp = emp_ret + emp_off + emp_pub + emp_ind + emp_ag + emp_military

    This is the final base_canvas equivalent — the end state of the
    full 11-step ETL pipeline.

    Materialized as: view
#}
{{ config(materialized=var('base_canvas_materialized', 'view')) }}

WITH imputed AS (
    SELECT * FROM {{ ref('base_canvas_imputed') }}
)

SELECT
    parcel_id,
    geometry,
    county,
    land_development_category,
    built_form_key,
    intersection_density,
    area_gross,
    area_parcel,
    area_dev_condition,
    area_row,
    area_parcel_res,
    area_parcel_emp_ag,
    area_parcel_emp,
    area_parcel_mixed_use,
    area_parcel_no_use,
    -- Demographics
    pop,
    pop_groupquarter,
    hh,
    -- du = du_detsf + du_attsf + du_mf
    GREATEST(du_detsf + du_attsf + du_mf, du) AS du,
    GREATEST(du_detsf_sl + du_detsf_ll, du_detsf) AS du_detsf,
    du_detsf_sl,
    du_detsf_ll,
    du_attsf,
    GREATEST(du_mf2to4 + du_mf5p, du_mf) AS du_mf,
    du_mf2to4,
    du_mf5p,
    -- Employment aggregates
    COALESCE(emp_retail_services, 0) + COALESCE(emp_restaurant, 0)
        + COALESCE(emp_accommodation, 0) + COALESCE(emp_arts_entertainment, 0)
        + COALESCE(emp_other_services, 0) AS emp_ret,
    emp_retail_services,
    emp_restaurant,
    emp_accommodation,
    emp_arts_entertainment,
    emp_other_services,
    COALESCE(emp_office_services, 0) + COALESCE(emp_medical_services, 0) AS emp_off,
    emp_office_services,
    emp_medical_services,
    COALESCE(emp_public_admin, 0) + COALESCE(emp_education, 0) AS emp_pub,
    emp_public_admin,
    emp_education,
    COALESCE(emp_manufacturing, 0) + COALESCE(emp_wholesale, 0)
        + COALESCE(emp_transport_warehousing, 0) + COALESCE(emp_utilities, 0)
        + COALESCE(emp_construction, 0) AS emp_ind,
    emp_manufacturing,
    emp_wholesale,
    emp_transport_warehousing,
    emp_utilities,
    emp_construction,
    COALESCE(emp_agriculture, 0) + COALESCE(emp_extraction, 0) AS emp_ag,
    emp_agriculture,
    emp_extraction,
    -- Total employment
    COALESCE(emp_ret, 0) + COALESCE(emp_off, 0) + COALESCE(emp_pub, 0)
        + COALESCE(emp_ind, 0) + COALESCE(emp_ag, 0) + COALESCE(emp_military, 0) AS emp,
    emp_military,
    -- Building areas
    bldg_area_detsf_sl,
    bldg_area_detsf_ll,
    bldg_area_attsf,
    bldg_area_mf,
    bldg_area_retail_services,
    bldg_area_restaurant,
    bldg_area_accommodation,
    bldg_area_arts_entertainment,
    bldg_area_other_services,
    bldg_area_office_services,
    bldg_area_public_admin,
    bldg_area_education,
    bldg_area_medical_services,
    bldg_area_transport_warehousing,
    bldg_area_wholesale,
    -- Irrigation
    residential_irrigated_area,
    commercial_irrigated_area,
    -- Equity
    median_income,
    rent_burden_pct,
    pct_minority,
    pct_college_educated,
    cost_burden_pct
FROM imputed

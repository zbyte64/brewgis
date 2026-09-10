AUDIT (
  name is_base_canvas_compatible,
  dialect postgres
);
-- Structural contract: fails to even compile (Postgres raises "column does
-- not exist") if @this_model is missing any column required for a workspace
-- to adopt it as its base canvas.
--
-- This is a schema check, not a row-predicate check — referencing every
-- required column here means any model attaching this audit gets the
-- contract enforced at `sqlmesh plan` time, rather than downstream when a
-- workspace tries to select it (see
-- brewgis.workspace.services.base_canvas_schema.BaseCanvasSchema.COLUMN_NAMES,
-- the canonical column list this audit mirrors, and
-- brewgis.workspace.services.sqlmesh_tables.list_base_canvas_candidates,
-- the Django-side picker that re-checks the same contract at query time).
SELECT
    id, id_source, geography_id, geometry_key, geometry,
    land_development_category, land_use, assessor_use_code, built_form_key,
    intersection_density,
    area_gross, area_parcel, area_dev_condition, area_row,
    area_parcel_res_detsf, area_parcel_res_detsf_sl, area_parcel_res_detsf_ll,
    area_parcel_res_attsf, area_parcel_res_mf, area_parcel_res,
    area_parcel_emp, area_parcel_emp_ret, area_parcel_emp_off,
    area_parcel_emp_pub, area_parcel_emp_ind, area_parcel_emp_ag,
    area_parcel_emp_military,
    area_parcel_mixed_use, area_parcel_no_use,
    pop, pop_groupquarter, hh, du,
    median_income, rent_burden_pct, pct_minority, pct_college_educated,
    cost_burden_pct,
    du_detsf, du_detsf_sl, du_detsf_ll, du_attsf, du_mf, du_mf2to4, du_mf5p,
    emp, emp_ret, emp_retail_services, emp_restaurant, emp_accommodation,
    emp_arts_entertainment, emp_other_services,
    emp_off, emp_office_services, emp_medical_services,
    emp_pub, emp_public_admin, emp_education,
    emp_ind, emp_manufacturing, emp_wholesale, emp_transport_warehousing,
    emp_utilities, emp_construction,
    emp_ag, emp_agriculture, emp_extraction, emp_military,
    bldg_area_detsf_sl, bldg_area_detsf_ll, bldg_area_attsf, bldg_area_mf,
    bldg_area_retail_services, bldg_area_restaurant, bldg_area_accommodation,
    bldg_area_arts_entertainment, bldg_area_other_services,
    bldg_area_office_services, bldg_area_public_admin, bldg_area_education,
    bldg_area_medical_services, bldg_area_transport_warehousing,
    bldg_area_wholesale,
    residential_irrigated_area, commercial_irrigated_area
FROM @this_model
WHERE FALSE;

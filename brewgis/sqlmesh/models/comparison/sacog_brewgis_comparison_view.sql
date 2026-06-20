MODEL (
  name brewgis.comparison.sacog_brewgis_comparison_view,
  kind FULL,
  audits (
    not_null(columns := (parcel_id))
  )
);

-- SACOG BrewGIS Comparison View — wraps base_canvas_reconciled with geography_id
-- and NULL columns for detailed area breakdowns needed by correlation models.

SELECT
    bcr.parcel_id,
    bcr.geometry,
    bcr.county,
    bcr.land_development_category,
    bcr.built_form_key,
    bcr.intersection_density,
    bcr.area_gross,
    bcr.area_gross_acres,
    bcr.area_parcel_acres,
    bcr.area_dev_condition_acres,
    bcr.area_row_acres,
    bcr.area_parcel_res,
    bcr.area_parcel_res_acres,
    bcr.area_parcel_emp_ag,
    bcr.area_parcel_emp_ag_acres,
    bcr.area_parcel_emp,
    bcr.area_parcel_emp_acres,
    bcr.area_parcel_mixed_use,
    bcr.area_parcel_mixed_use_acres,
    bcr.area_parcel_no_use,
    bcr.area_parcel_no_use_acres,
    bcr.pop,
    bcr.pop_groupquarter,
    bcr.hh,
    bcr.du,
    bcr.du_detsf,
    bcr.du_detsf_sl,
    bcr.du_detsf_ll,
    bcr.du_attsf,
    bcr.du_mf,
    bcr.du_mf2to4,
    bcr.du_mf5p,
    bcr.emp_ret,
    bcr.emp_retail_services,
    bcr.emp_restaurant,
    bcr.emp_accommodation,
    bcr.emp_arts_entertainment,
    bcr.emp_other_services,
    bcr.emp_off,
    bcr.emp_office_services,
    bcr.emp_medical_services,
    bcr.emp_pub,
    bcr.emp_public_admin,
    bcr.emp_education,
    bcr.emp_ind,
    bcr.emp_manufacturing,
    bcr.emp_wholesale,
    bcr.emp_transport_warehousing,
    bcr.emp_utilities,
    bcr.emp_construction,
    bcr.emp_ag,
    bcr.emp_agriculture,
    bcr.emp_extraction,
    bcr.emp,
    bcr.emp_military,
    bcr.bldg_area_detsf_sl,
    bcr.bldg_area_detsf_ll,
    bcr.bldg_area_attsf,
    bcr.bldg_area_mf,
    bcr.bldg_area_retail_services,
    bcr.bldg_area_restaurant,
    bcr.bldg_area_accommodation,
    bcr.bldg_area_arts_entertainment,
    bcr.bldg_area_other_services,
    bcr.bldg_area_office_services,
    bcr.bldg_area_public_admin,
    bcr.bldg_area_education,
    bcr.bldg_area_medical_services,
    bcr.bldg_area_transport_warehousing,
    bcr.bldg_area_wholesale,
    bcr.residential_irrigated_area,
    bcr.commercial_irrigated_area,
    bcr.median_income,
    bcr.rent_burden_pct,
    bcr.pct_minority,
    bcr.pct_college_educated,
    bcr.cost_burden_pct,
    NULL::double precision AS area_parcel_res_detsf,
    NULL::double precision AS area_parcel_res_detsf_sl,
    NULL::double precision AS area_parcel_res_detsf_ll,
    NULL::double precision AS area_parcel_res_attsf,
    NULL::double precision AS area_parcel_res_mf,
    NULL::double precision AS area_parcel_emp_ret,
    NULL::double precision AS area_parcel_emp_off,
    NULL::double precision AS area_parcel_emp_pub,
    NULL::double precision AS area_parcel_emp_ind,
    NULL::double precision AS area_parcel_emp_military,
    sp.geography_id
FROM brewgis.base_canvas.base_canvas_reconciled bcr
LEFT JOIN public.sacog_comparison_parcels sp
    ON bcr.parcel_id = sp.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_sacog_brewgis_comparison_view_geom
  ON brewGIS.comparison.sacog_brewgis_comparison_view USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_comparison_view_parcel_id
  ON brewgis.comparison.sacog_brewgis_comparison_view (parcel_id);
  CREATE INDEX IF NOT EXISTS idx_comparison_view_geography_id
  ON brewgis.comparison.sacog_brewgis_comparison_view (geography_id);

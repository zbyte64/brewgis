MODEL (
  name brewgis.comparison.sacog_brewgis_comparison_view,
  kind VIEW
);

-- SACOG BrewGIS Comparison View — wraps base_canvas_reconciled with geography_id
-- and NULL columns for detailed area breakdowns needed by correlation models.

SELECT
    bcr.*,
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
FROM base_canvas_reconciled bcr
LEFT JOIN public.sacog_comparison_parcels sp
    ON bcr.parcel_id = sp.parcel_id

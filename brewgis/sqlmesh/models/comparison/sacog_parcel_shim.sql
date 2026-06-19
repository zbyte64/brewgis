MODEL (
  name brewgis.comparison.sacog_parcel_shim,
  kind FULL,
  audits (
    not_null(columns := (parcel_id)),
    unique_values(columns := (parcel_id,))
  )
);

-- SACOG Parcel Column Shim — maps SACOG v1 columns to brewgis-standard column names.
--
-- Reads raw SACOG parcel data from public.sacog_comparison_parcels and produces
-- a table with brewgis-compatible column names so that base_canvas_geometry and
-- the rest of the base_canvas chain can consume SACOG v1 data.
-- should not reveal any statistical information, we get that from our data sources

SELECT
    parcel_id,
    ST_MakeValid(ST_Transform(geometry, @VAR('default_srid', 4326))) AS geometry,
    ST_MakeValid(geometry) AS local_geometry,
    'Sacramento'::text AS county,
    NULL::text AS land_development_category,
    NULL::text AS built_form_key,
    NULL::double precision AS intersection_density,
    NULL::double precision AS pop,
    NULL::double precision AS hh,
    NULL::double precision AS du,
    NULL::double precision AS emp,
    NULL::text AS land_use,
    NULL::text AS assessor_use_code,
    NULL::double precision AS acres,
    NULL::double precision AS ret,
    NULL::double precision AS off,
    NULL::double precision AS pub,
    NULL::double precision AS ind,
    NULL::double precision AS other,
    NULL::text AS jurisdiction,
    NULL::text AS gp,
    NULL::text AS gluc,
    NULL::text AS census_blockgroup,
    NULL::text AS census_block,
    NULL::text AS notes,
    NULL::double precision AS bldg_area_detsf_sl,
    NULL::double precision AS bldg_area_detsf_ll,
    NULL::double precision AS bldg_area_attsf,
    NULL::double precision AS bldg_area_mf,
    NULL::double precision AS bldg_area_retail_services,
    NULL::double precision AS bldg_area_restaurant,
    NULL::double precision AS bldg_area_accommodation,
    NULL::double precision AS bldg_area_arts_entertainment,
    NULL::double precision AS bldg_area_other_services,
    NULL::double precision AS bldg_area_office_services,
    NULL::double precision AS bldg_area_public_admin,
    NULL::double precision AS bldg_area_education,
    NULL::double precision AS bldg_area_medical_services,
    NULL::double precision AS bldg_area_transport_warehousing,
    NULL::double precision AS bldg_area_wholesale,
    NULL::double precision AS residential_irrigated_area,
    NULL::double precision AS commercial_irrigated_area,
    NULL::double precision AS area_parcel_res,
    NULL::double precision AS area_parcel_emp_ag,
    NULL::double precision AS area_parcel_emp,
    NULL::double precision AS area_parcel_mixed_use,
    NULL::double precision AS area_parcel_no_use
FROM public.sacog_comparison_parcels;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_sacog_parcel_shim_geometry
  ON brewgis.comparison.sacog_parcel_shim USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_sacog_parcel_shim_parcel_id
  ON brewgis.comparison.sacog_parcel_shim (parcel_id);
ANALYZE brewgis.comparison.sacog_parcel_shim;

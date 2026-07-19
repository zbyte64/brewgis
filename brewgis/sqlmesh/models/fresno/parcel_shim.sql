MODEL (
  name brewgis.fresno.parcel_shim,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  audits (
    not_null(columns := (parcel_id)),
    unique_values(columns := (parcel_id,))
  )
);

-- Fresno Parcel Column Shim — maps Fresno GeoJSON parcel columns to standard contract.
--
-- Reads raw Fresno parcel data from fresno_demo.fresno_parcels and produces
-- a table with the same output columns as sacog_parcel_shim so that
-- base_canvas_geometry and other downstream models can process Fresno data.
--
-- Fresno parcels lack assessor data, so all assessor-derived columns are NULL.

SELECT
    parcel_id,
    ST_MakeValid(geometry) AS geometry,
    ST_Transform(ST_MakeValid(geometry), @VAR('local_srid', 3310)) AS local_geometry,
    'Fresno'::text AS county,
    'urban'::text AS land_development_category,
    NULL::text AS built_form_key,
    NULL::double precision AS intersection_density,
    NULL::double precision AS pop,
    NULL::double precision AS hh,
    NULL::double precision AS du,
    NULL::double precision AS emp,
    NULL::text AS land_use,
    NULL::text AS assessor_use_code,
    -- acres computed from geometry
    ROUND((ST_Area(ST_Transform(ST_MakeValid(geometry), @VAR('local_srid', 3310))) / 4046.86)::numeric, 4)
        AS acres,
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
FROM brewgis.fresno_demo.fresno_parcels;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_fresno_parcel_shim_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_fresno_parcel_shim_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;

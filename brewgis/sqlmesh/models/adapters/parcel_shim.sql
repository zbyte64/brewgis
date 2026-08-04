MODEL (
  name brewgis.@{region}.parcel_shim,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  audits (
    not_null(columns := (parcel_id)),
    unique_values(columns := (parcel_id,)),
    assert_row_count_greater_than_zero
  ),
  blueprints (
    (region := sacog,  source_schema := 'public',      source_table := 'sacog_comparison_parcels', county_name := 'Sacramento'),
    (region := fresno, source_schema := 'fresno_demo', source_table := 'fresno_parcels',            county_name := 'Fresno')
  )
);

-- Region Parcel Column Shim — the sole raw-parcel adapter.
--
-- Maps each region's raw parcel table onto the standard 42-column brewgis
-- parcel contract consumed by every downstream methodology model. The only
-- region-specific inputs are the source table and county name (blueprint
-- variables); the SQL body is identical for all regions.
--
-- geometry       — global WGS84 (4326), transformed from the source SRID
-- local_geometry — local projected SRID (3310 CA Albers) for area/join work
-- acres          — area from local_geometry (Fresno parcels rely on this for
--                  lot_size_acres since they lack assessor data)

SELECT
    parcel_id,
    ST_MakeValid(ST_Transform(geometry, @VAR('default_srid', 4326))) AS geometry,
    ST_Transform(ST_MakeValid(geometry), @VAR('local_srid', 3310)) AS local_geometry,
    @county_name::text AS county,
    NULL::text AS land_development_category,
    NULL::text AS built_form_key,
    NULL::double precision AS intersection_density,
    NULL::double precision AS pop,
    NULL::double precision AS hh,
    NULL::double precision AS du,
    NULL::double precision AS emp,
    NULL::text AS land_use,
    NULL::text AS assessor_use_code,
    -- acres computed from local_geometry area
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
FROM @{source_schema}.@{source_table};

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_@{region}_parcel_shim_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_@{region}_parcel_shim_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
  ANALYZE @this_model;

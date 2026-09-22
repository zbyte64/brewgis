MODEL (
  name brewgis.@{region}.parcel_shim,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  description 'Region parcel shim: raw region parcel tables mapped to the standard parcel contract.',
  column_descriptions (
    parcel_id = 'Parcel identifier from the region source parcel table.',
    geometry = 'Parcel boundary in WGS84 (EPSG:4326), repaired with ST_MakeValid.',
    local_geometry = 'Parcel boundary reprojected to the local SRID (3310 CA Albers) for area and join work.',
    county = 'County name supplied by the region blueprint.',
    land_development_category = 'Land development category of the parcel; NULL here, filled downstream.',
    built_form_key = 'Built form classification key of the parcel; NULL here, filled downstream.',
    intersection_density = 'Intersection density around the parcel (per km2); NULL here, filled downstream.',
    pop = 'Total population of the parcel (people); NULL here, filled downstream.',
    hh = 'Households on the parcel (count); NULL here, filled downstream.',
    du = 'Dwelling units on the parcel (count); NULL here, filled downstream.',
    emp = 'Total employment on the parcel (jobs); NULL here, filled downstream.',
    land_use = 'Land use code of the parcel from the region source table; NULL in the shim.',
    assessor_use_code = 'County assessor use code of the parcel; NULL here, filled downstream.',
    acres = 'Parcel area computed from local_geometry (acres, 4 decimals).',
    ret = 'Retail employment on the parcel (jobs); NULL here, filled downstream.',
    off = 'Office employment on the parcel (jobs); NULL here, filled downstream.',
    pub = 'Public employment on the parcel (jobs); NULL here, filled downstream.',
    ind = 'Industrial employment on the parcel (jobs); NULL here, filled downstream.',
    other = 'Employment in other sectors on the parcel (jobs); NULL here, filled downstream.',
    jurisdiction = 'Jurisdiction the parcel lies in; NULL here, filled downstream.',
    gp = 'Legacy gp field of the parcel contract, unused downstream; NULL in the shim.',
    gluc = 'Legacy gluc field of the parcel contract, unused downstream; NULL in the shim.',
    census_blockgroup = 'Census block group GEOID of the parcel; NULL here, filled downstream.',
    census_block = 'Census block GEOID of the parcel; NULL here, filled downstream.',
    notes = 'Free-form notes on the parcel from the region source table; NULL in the shim.',
    bldg_area_detsf_sl = 'Detached SF small lot building area (sq ft); NULL here, filled downstream.',
    bldg_area_detsf_ll = 'Detached SF large lot building area (sq ft); NULL here, filled downstream.',
    bldg_area_attsf = 'Attached SF building area (sq ft); NULL here, filled downstream.',
    bldg_area_mf = 'Multi-family building area (sq ft); NULL here, filled downstream.',
    bldg_area_retail_services = 'Retail services building area (sq ft); NULL here, filled downstream.',
    bldg_area_restaurant = 'Restaurant building area (sq ft); NULL here, filled downstream.',
    bldg_area_accommodation = 'Accommodation building area (sq ft); NULL here, filled downstream.',
    bldg_area_arts_entertainment = 'Arts and entertainment building area (sq ft); NULL here, filled downstream.',
    bldg_area_other_services = 'Other services building area (sq ft); NULL here, filled downstream.',
    bldg_area_office_services = 'Office services building area (sq ft); NULL here, filled downstream.',
    bldg_area_public_admin = 'Public administration building area (sq ft); NULL here, filled downstream.',
    bldg_area_education = 'Education building area (sq ft); NULL here, filled downstream.',
    bldg_area_medical_services = 'Medical services building area (sq ft); NULL here, filled downstream.',
    bldg_area_transport_warehousing = 'Transport and warehousing building area (sq ft); NULL here, filled downstream.',
    bldg_area_wholesale = 'Wholesale building area (sq ft); NULL here, filled downstream.',
    residential_irrigated_area = 'Residential irrigated area (acres); NULL here, filled downstream.',
    commercial_irrigated_area = 'Commercial irrigated area (acres); NULL here, filled downstream.',
    area_parcel_res = 'Total residential parcel area (acres); NULL here, filled downstream.',
    area_parcel_emp_ag = 'Agricultural employment parcel area (acres); NULL here, filled downstream.',
    area_parcel_emp = 'Total employment parcel area (acres); NULL here, filled downstream.',
    area_parcel_mixed_use = 'Mixed use parcel area (acres); NULL here, filled downstream.',
    area_parcel_no_use = 'No use parcel area (acres); NULL here, filled downstream.'
  ),
  audits (
    not_null(columns := (parcel_id)),
    unique_values(columns := (parcel_id,)),
    assert_row_count_greater_than_zero
  ),
  blueprints @region_blueprints()
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
FROM @IF(@source, @ref_model(@source), @{source_schema}.@{source_table});

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_parcel_shim_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_parcel_shim_parcel_id_')
  ON @this_model USING btree (parcel_id);
  ANALYZE @this_model;

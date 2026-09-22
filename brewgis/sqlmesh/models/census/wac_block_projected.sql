MODEL (
  name brewgis.@{region}.wac_block_projected,
  kind FULL,
  description 'wac_block with block geometry pre-projected to the local SRID (@VAR local_srid, default 3310) plus its envelope, so spatial joins skip the transform, one row per block.',
  column_descriptions (
    geoid = '15-digit census block GEOID (state+county+tract+block FIPS), carried through from wac_block.',
    geometry = 'Block geometry in EPSG:4326, carried through from wac_block.',
    emp = 'Total employment of the block (jobs) as published by wac_block.',
    emp_agriculture = 'Agricultural employment (jobs) as published by wac_block.',
    emp_extraction = 'Extraction employment (jobs) as published by wac_block.',
    emp_construction = 'Construction employment (jobs) as published by wac_block.',
    emp_manufacturing = 'Manufacturing employment (jobs) as published by wac_block.',
    emp_transport_warehousing = 'Transport/warehousing employment (jobs) as published by wac_block.',
    emp_utilities = 'Utilities employment (jobs) as published by wac_block.',
    emp_wholesale = 'Wholesale employment (jobs) as published by wac_block.',
    emp_retail_services = 'Retail services employment (jobs) as published by wac_block.',
    emp_office_services = 'Office services employment (jobs) as published by wac_block.',
    emp_education = 'Education employment (jobs) as published by wac_block.',
    emp_medical_services = 'Medical services employment (jobs) as published by wac_block.',
    emp_arts_entertainment = 'Arts and entertainment employment (jobs) as published by wac_block.',
    emp_accommodation = 'Accommodation employment (jobs) as published by wac_block.',
    emp_restaurant = 'Restaurant employment (jobs) as published by wac_block.',
    emp_other_services = 'Other services employment (jobs) as published by wac_block.',
    emp_public_admin = 'Public administration employment (jobs) as published by wac_block.',
    emp_military = 'Military employment (jobs) as published by wac_block.',
    emp_ret = 'Retail employment (jobs) as published by wac_block.',
    emp_off = 'Office employment (jobs) as published by wac_block.',
    emp_pub = 'Public employment (jobs) as published by wac_block.',
    emp_ind = 'Industrial employment (jobs) as published by wac_block.',
    emp_ag = 'Agricultural employment (jobs) as published by wac_block.',
    local_geometry = 'Block geometry reprojected to the local SRID (@VAR local_srid, default 3310).',
    wac_envelope = 'Bounding box of the local-SRID block geometry, used for indexed spatial prefilters.'
  ),
  audits (
    not_null(columns := (geoid))
  ),
  blueprints @region_blueprints()
);

-- WAC Block Projected — pre-projected geometry for indexed spatial joins.
--
-- Pre-computes local_srid (3310) geometry and envelope so base_canvas_employment
-- avoids repeated ST_Transform + ST_Envelope during spatial joins.
-- kind FULL with GiST index for fast ST_Intersects lookups.

SELECT
    w.geoid,
    w.geometry,
    w.emp,
    w.emp_agriculture,
    w.emp_extraction,
    w.emp_construction,
    w.emp_manufacturing,
    w.emp_transport_warehousing,
    w.emp_utilities,
    w.emp_wholesale,
    w.emp_retail_services,
    w.emp_office_services,
    w.emp_education,
    w.emp_medical_services,
    w.emp_arts_entertainment,
    w.emp_accommodation,
    w.emp_restaurant,
    w.emp_other_services,
    w.emp_public_admin,
    w.emp_military,
    w.emp_ret,
    w.emp_off,
    w.emp_pub,
    w.emp_ind,
    w.emp_ag,
    ST_Transform(w.geometry, @VAR('local_srid', 3310)) AS local_geometry,
    ST_Envelope(ST_Transform(w.geometry, @VAR('local_srid', 3310))) AS wac_envelope
FROM brewgis.@{region}.wac_block w
WHERE w.geometry IS NOT NULL;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_wac_block_proj_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_wac_block_proj_geoid_')
  ON @this_model USING btree (geoid);
ANALYZE @this_model;

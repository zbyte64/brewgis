MODEL (
  name brewgis.staging.wac_block_projected,
  kind FULL,
  audits (
    not_null(columns := (geoid))
  )
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
FROM brewgis.staging.wac_block w
WHERE w.geometry IS NOT NULL;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_wac_block_proj_geometry
  ON brewgis.staging.wac_block_projected USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_wac_block_proj_geoid
  ON brewgis.staging.wac_block_projected (geoid);
ANALYZE brewgis.staging.wac_block_projected;

MODEL (
  name brewgis.staging.census_2020_block_projected,
  kind FULL,
  audits (
    not_null(columns := (geoid))
  )
);

-- Census 2020 Block Projected — pre-projected geometry for indexed spatial joins.
--
-- Pre-computes local_srid (3310) geometry and envelope so base_canvas_demographics
-- avoids repeated ST_Transform + ST_Envelope during spatial joins.
-- kind FULL with GiST index for fast ST_Intersects lookups.

SELECT
    geoid,
    total_population,
    total_housing_units,
    geometry,
    ST_Transform(geometry, @VAR('local_srid', 3310)) AS local_geometry,
    ST_Envelope(ST_Transform(geometry, @VAR('local_srid', 3310))) AS local_envelope
FROM brewgis.staging.census_2020_block
WHERE geometry IS NOT NULL;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_c2020_block_proj_geometry
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_c2020_block_proj_geoid
  ON @this_model USING btree (geoid);
ANALYZE @this_model;

MODEL (
  name brewgis.@{region}.census_2020_block_projected,
  kind FULL,
  description 'Census 2020 blocks with pre-projected local state plane geometry and envelope for spatial joins.',
  column_descriptions (
    geoid = 'Census block GEOID (15-digit FIPS).',
    total_population = 'Total population of the block carried through from the census_2020_block model (people).',
    total_housing_units = 'Total housing units carried through from the census_2020_block model (housing units).',
    geometry = 'Block boundary in SRID 4326 (degrees, EPSG:4326).',
    local_geometry = 'Block boundary transformed to the local state plane CRS from local_srid, default 3310.',
    local_envelope = 'Bounding envelope of local_geometry in the local state plane CRS, for fast spatial preselection.'
  ),
  audits (
    not_null(columns := (geoid))
  ),
  blueprints @region_blueprints()
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
FROM brewgis.@{region}.census_2020_block
WHERE geometry IS NOT NULL;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_c2020_block_proj_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_c2020_block_proj_geoid_')
  ON @this_model USING btree (geoid);
ANALYZE @this_model;

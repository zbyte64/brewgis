MODEL (
  name brewgis.@{region}.census_2020_block,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (geoid)
  ),
  description 'Census 2020 block population and housing units (PL 94-171) with TIGER/Line block geometry.',
  column_descriptions (
    geoid = 'Census block GEOID (15-digit FIPS), the unique key of the table.',
    total_population = 'Total population of the block from PL 94-171, zero when the API reported no value (people).',
    total_housing_units = 'Total housing units in the block from PL 94-171, zero when absent (housing units).',
    total_group_quarters = 'Group quarters population of the block, always 0 because PL 94-171 omits it (people).',
    geometry = 'Block boundary from TIGER/Line block vintage 2020, set to SRID 4326 (degrees, EPSG:4326).'
  ),
  audits (
    not_null(columns := (geoid))
  ),
  dialect postgres,
  blueprints @region_blueprints()
);

-- Census 2020 PL94-171 → Census Block Demographics Table
--
-- Joins decennial Census block raw data with TIGER/Line block geometry.
-- PL94-171 redistricting data provides total population and housing units
-- at the census block level, the finest granularity available.
--
-- Note: PL94-171 does not include group quarters population (SF1 did,
-- but was replaced by ACS for socioeconomics). The total_group_quarters
-- column is included for schema compatibility but will always be 0.

WITH raw_data AS (
    SELECT
        geoid,
        total_population,
        total_housing_units
    FROM brewgis.@{region}.census_2020_block_raw
),
block_geometry AS (
    SELECT
        geoid,
        ST_SetSRID(wgs84_geometry, 4326) AS geometry
    FROM brewgis.census.tiger_blocks
    WHERE vintage = '2020'
)
SELECT
    raw.geoid AS geoid,
    COALESCE(raw.total_population, 0)::double precision AS total_population,
    COALESCE(raw.total_housing_units, 0)::double precision AS total_housing_units,
    -- PL94-171 does not include group quarters population; always 0.
    0.0::double precision AS total_group_quarters,
    bg.geometry
FROM raw_data raw
LEFT JOIN block_geometry bg
    ON raw.geoid = bg.geoid;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_census_2020_block_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_census_2020_block_geoid_')
  ON @this_model USING btree (geoid);
ANALYZE @this_model;

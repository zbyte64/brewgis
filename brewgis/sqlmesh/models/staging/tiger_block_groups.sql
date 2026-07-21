MODEL (
  name duckdb.staging.tiger_block_groups,
  kind VIEW,
  gateway duckdb,
  dialect duckdb
);

-- TIGER/Line block group boundaries — DuckDB reads directly from Census
-- TIGER2023 and TIGER2013 shapefile ZIPs via the zipfs + httpfs extensions.
--
-- Both vintages are read via UNION ALL for backward compatibility.
--
-- Variables:
--   @state_fips  — Two-digit state FIPS code for URL construction

SELECT
  STATEFP || COUNTYFP || TRACTCE || BLKGRPCE AS geoid,
  ST_Transform(geometry, 'EPSG:4326') AS geometry,
  STATEFP AS state_fips,
  '2023' AS vintage
FROM ST_Read(
  'zip://https://www2.census.gov/geo/tiger/TIGER2023/BG/tl_2023_'
  || @state_fips
  || '_bg.zip/tl_2023_'
  || @state_fips
  || '_bg.shp'
)
WHERE STATEFP = @state_fips

UNION ALL

SELECT
  STATEFP10 || COUNTYFP10 || TRACTCE10 || BLKGRPCE10 AS geoid,
  ST_Transform(geometry, 'EPSG:4326') AS geometry,
  STATEFP10 AS state_fips,
  '2013' AS vintage
FROM ST_Read(
  'zip://https://www2.census.gov/geo/tiger/TIGER2013/BG/tl_2013_'
  || @state_fips
  || '_bg.zip/tl_2013_'
  || @state_fips
  || '_bg.shp'
)
WHERE STATEFP10 = @state_fips;

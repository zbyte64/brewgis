MODEL (
  name duckdb.staging.tiger_blocks,
  kind VIEW,
  gateway duckdb,
  dialect duckdb
);

-- TIGER/Line census block boundaries — DuckDB reads directly from Census
-- TIGER2020 shapefile ZIPs via the zipfs + httpfs extensions.
--
-- Variables:
--   @state_fips  — Two-digit state FIPS code for URL construction

SELECT
  STATEFP20 || COUNTYFP20 || TRACTCE20 || BLOCKCE20 AS geoid,
  ST_Transform(geometry, 'EPSG:4326') AS geometry,
  STATEFP20 AS state_fips,
  '2020' AS vintage
FROM ST_Read(
  'zip://https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_'
  || @state_fips
  || '_tabblock20.zip/tl_2020_'
  || @state_fips
  || '_tabblock20.shp'
)
WHERE STATEFP20 = @state_fips;

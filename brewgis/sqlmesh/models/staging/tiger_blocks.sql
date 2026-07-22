MODEL (
  name duckdb.staging.tiger_blocks,
  kind VIEW,
  gateway duckdb,
  dialect duckdb
);

-- TIGER/Line census block boundaries — DuckDB reads directly from Census FTP
-- ZIP files via the zipfs community extension (zip:// protocol).
--
-- Source CRS: EPSG:4269 (NAD83). Census TIGER/Line 2020 block shapefiles via zipfs.
-- ST_Transform with always_xy=true ensures (lon,lat) input axis order.
-- EPSG:3857 output is Web Mercator (x,y) with no axis ambiguity.
-- EPSG:4326 output is geographic (lon,lat) for spatial joins.
--
-- Variables:
--   @state_fips  — Two-digit state FIPS code

WITH blocks_raw AS (
  SELECT STATEFP20, COUNTYFP20, TRACTCE20, BLOCKCE20, geom
  FROM ST_Read(
    'zip://https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_'
    || @state_fips
    || '_tabblock20.zip/tl_2020_'
    || @state_fips
    || '_tabblock20.shp'
  )
  WHERE STATEFP20 = @state_fips
)
SELECT
  STATEFP20 || COUNTYFP20 || TRACTCE20 || BLOCKCE20 AS geoid,
  ST_Transform(geom, 'EPSG:4269', 'EPSG:3857', true) AS geometry,
  ST_Transform(geom, 'EPSG:4269', 'EPSG:4326', true) AS wgs84_geometry,
  STATEFP20 AS state_fips,
  '2020' AS vintage
FROM blocks_raw;

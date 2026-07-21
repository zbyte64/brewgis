MODEL (
  name duckdb.staging.tiger_block_groups,
  kind VIEW,
  gateway duckdb,
  dialect duckdb
);

-- TIGER/Line block group boundaries — DuckDB reads directly from Census FTP
-- ZIP files via the zipfs community extension (zip:// protocol).
--
-- Both vintages are read via UNION ALL for backward compatibility.
--
-- Variables:
--   @state_fips  — Two-digit state FIPS code

WITH bg_2023_raw AS (
  SELECT STATEFP, COUNTYFP, TRACTCE, BLKGRPCE, geom
  FROM ST_Read(
    'zip://https://www2.census.gov/geo/tiger/TIGER2023/BG/tl_2023_'
    || @state_fips
    || '_bg.zip/tl_2023_'
    || @state_fips
    || '_bg.shp'
  )
  WHERE STATEFP = @state_fips
),
bg_2023 AS (
  SELECT
    STATEFP || COUNTYFP || TRACTCE || BLKGRPCE AS geoid,
    ST_Transform(geom, 'EPSG:4326') AS geometry,
    STATEFP AS state_fips,
    '2023' AS vintage
  FROM bg_2023_raw
),
bg_2013_raw AS (
  SELECT STATEFP, COUNTYFP, TRACTCE, BLKGRPCE, geom
  FROM ST_Read(
    'zip://https://www2.census.gov/geo/tiger/TIGER2013/BG/tl_2013_'
    || @state_fips
    || '_bg.zip/tl_2013_'
    || @state_fips
    || '_bg.shp'
  )
  WHERE STATEFP = @state_fips
),
bg_2013 AS (
  SELECT
    STATEFP || COUNTYFP || TRACTCE || BLKGRPCE AS geoid,
    ST_Transform(geom, 'EPSG:4326') AS geometry,
    STATEFP AS state_fips,
    '2013' AS vintage
  FROM bg_2013_raw
)
SELECT geoid, geometry, state_fips, vintage FROM bg_2023
UNION ALL
SELECT geoid, geometry, state_fips, vintage FROM bg_2013;

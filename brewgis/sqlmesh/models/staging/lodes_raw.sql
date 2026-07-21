MODEL (
  name duckdb.staging.lodes_raw,
  kind VIEW,
  gateway duckdb,
  dialect duckdb
);

-- LEHD LODES WAC raw data — DuckDB reads gzipped CSV from CES FTP via httpfs.
--
-- The LEHD API provides per-state gzipped CSV files at:
--   https://lehd.ces.census.gov/data/lodes/LODES8/{state_abbr}/wac/
--   {state_abbr}_wac_S000_JT00_{year}.csv.gz
--
-- This model builds the URL from the FIPS code using a CASE expression
-- for the FIPS-to-state-abbreviation mapping (sourced from _FIPS_TO_STATE
-- in lehd_fetcher.py).
--
-- Variables:
--   @lodes_year    — LEHD LODES release year (default 2008)
--   @state_fips    — Two-digit state FIPS code (default '06')
--   @county_fips   — Three-digit county code for row-level filtering

WITH fips_to_abbr AS (
  SELECT CASE @state_fips
    WHEN '01' THEN 'al' WHEN '02' THEN 'ak' WHEN '04' THEN 'az'
    WHEN '05' THEN 'ar' WHEN '06' THEN 'ca' WHEN '08' THEN 'co'
    WHEN '09' THEN 'ct' WHEN '10' THEN 'de' WHEN '11' THEN 'dc'
    WHEN '12' THEN 'fl' WHEN '13' THEN 'ga' WHEN '15' THEN 'hi'
    WHEN '16' THEN 'id' WHEN '17' THEN 'il' WHEN '18' THEN 'in'
    WHEN '19' THEN 'ia' WHEN '20' THEN 'ks' WHEN '21' THEN 'ky'
    WHEN '22' THEN 'la' WHEN '23' THEN 'me' WHEN '24' THEN 'md'
    WHEN '25' THEN 'ma' WHEN '26' THEN 'mi' WHEN '27' THEN 'mn'
    WHEN '28' THEN 'ms' WHEN '29' THEN 'mo' WHEN '30' THEN 'mt'
    WHEN '31' THEN 'ne' WHEN '32' THEN 'nv' WHEN '33' THEN 'nh'
    WHEN '34' THEN 'nj' WHEN '35' THEN 'nm' WHEN '36' THEN 'ny'
    WHEN '37' THEN 'nc' WHEN '38' THEN 'nd' WHEN '39' THEN 'oh'
    WHEN '40' THEN 'ok' WHEN '41' THEN 'or' WHEN '42' THEN 'pa'
    WHEN '44' THEN 'ri' WHEN '45' THEN 'sc' WHEN '46' THEN 'sd'
    WHEN '47' THEN 'tn' WHEN '48' THEN 'tx' WHEN '49' THEN 'ut'
    WHEN '50' THEN 'vt' WHEN '51' THEN 'va' WHEN '53' THEN 'wa'
    WHEN '54' THEN 'wv' WHEN '55' THEN 'wi' WHEN '56' THEN 'wy'
    WHEN '60' THEN 'as' WHEN '66' THEN 'gu' WHEN '69' THEN 'mp'
    WHEN '72' THEN 'pr' WHEN '74' THEN 'um' WHEN '78' THEN 'vi'
    ELSE ''
  END AS state_abbr
)
SELECT
  CAST(@lodes_year AS INTEGER) AS year,
  w_geocode,
  c000::BIGINT AS c000,
  cns01::BIGINT AS cns01,
  cns02::BIGINT AS cns02,
  cns03::BIGINT AS cns03,
  cns04::BIGINT AS cns04,
  cns05::BIGINT AS cns05,
  cns06::BIGINT AS cns06,
  cns07::BIGINT AS cns07,
  cns08::BIGINT AS cns08,
  cns09::BIGINT AS cns09,
  cns10::BIGINT AS cns10,
  cns11::BIGINT AS cns11,
  cns12::BIGINT AS cns12,
  cns13::BIGINT AS cns13,
  cns14::BIGINT AS cns14,
  cns15::BIGINT AS cns15,
  cns16::BIGINT AS cns16,
  cns17::BIGINT AS cns17,
  cns18::BIGINT AS cns18,
  cns19::BIGINT AS cns19,
  cns20::BIGINT AS cns20
FROM fips_to_abbr,
LATERAL (
  SELECT *
  FROM read_csv_auto(
    'https://lehd.ces.census.gov/data/lodes/LODES8/'
    || fips_to_abbr.state_abbr || '/wac/' || fips_to_abbr.state_abbr
    || '_wac_S000_JT00_' || CAST(@lodes_year AS VARCHAR) || '.csv.gz',
    header = true,
    delim = ',',
    all_varchar = true
  )
)
WHERE LEFT(w_geocode, 5) = CONCAT(@state_fips, @county_fips);

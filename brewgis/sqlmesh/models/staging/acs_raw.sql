MODEL (
  name duckdb.staging.acs_raw,
  kind VIEW,
  gateway duckdb,
  dialect duckdb
);

-- Census ACS 5-year raw data — DuckDB reads directly from Census API via httpfs.
--
-- The Census API returns JSON in the format: [[headers], [row1], [row2], ...].
-- Each row is a flat array of strings.  This model uses read_json_auto with
-- format='array' to parse the response, skips the header row, and maps
-- columns by position (DuckDB list indexing is 1-based).
--
-- Columns 1-40 are ACS variables (in get= parameter order).
-- Columns 41-44 are geography columns: state, county, tract, block_group.
-- Variables are listed in the same order as _all_vars() in census_fetcher.py.
--
-- Variables (from SQLMesh @VAR macro — set in config.py):
--   @acs_year        — ACS 5-year data year (default 2022)
--   @state_fips      — Two-digit state FIPS code (default '06')
--   @county_fips     — Three-digit county code; supports '*' for all counties
--   @census_api_key  — Census API key; empty string skips the &key= param
SET allow_asterisks_in_http_paths = true;

WITH api_response AS MATERIALIZED (
  SELECT *
  FROM read_json_auto(
    'https://api.census.gov/data/' || CAST(@acs_year AS VARCHAR) || '/acs/acs5'
    || '?get=B01001_001E'
    || ',B25003_001E,B25003_002E,B25003_003E'
    || ',B25024_001E,B25024_002E,B25024_003E,B25024_004E,B25024_005E'
    || ',B25024_006E,B25024_007E,B25024_008E,B25024_009E'
    || ',B25008_001E,B25008_002E,B25008_003E'
    || ',B19013_001E'
    || ',B25070_001E,B25070_007E,B25070_008E,B25070_009E,B25070_010E'
    || ',B25091_001E,B25091_005E,B25091_006E,B25091_007E'
    || ',B25091_011E,B25091_012E,B25091_013E'
    || ',B03002_001E,B03002_002E,B03002_003E,B03002_004E,B03002_005E,B03002_012E'
    || ',B15003_001E,B15003_022E,B15003_023E,B15003_024E,B15003_025E'
    || '&for=block+group:*&in=state:' || @state_fips || '+tract:*'
    || CASE WHEN @county_fips <> '*' THEN '+county:' || @county_fips ELSE '' END
    || CASE WHEN @census_api_key <> '' THEN '&key=' || @census_api_key ELSE '' END,
    format = 'array'
  )
),
numbered AS (
  SELECT
    ROW_NUMBER() OVER () AS rn,
    json
  FROM api_response
)
SELECT
  CAST(@acs_year AS INTEGER) AS year,
  json[41]::VARCHAR AS state,
  json[42]::VARCHAR AS county,
  json[43]::VARCHAR AS tract,
  json[44]::VARCHAR AS block_group,
  NULLIF(json[1]::VARCHAR, '')::BIGINT  AS b01001_001_e,
  NULLIF(json[2]::VARCHAR, '')::BIGINT  AS b25003_001_e,
  NULLIF(json[3]::VARCHAR, '')::BIGINT  AS b25003_002_e,
  NULLIF(json[4]::VARCHAR, '')::BIGINT  AS b25003_003_e,
  NULLIF(json[5]::VARCHAR, '')::BIGINT  AS b25024_001_e,
  NULLIF(json[6]::VARCHAR, '')::BIGINT  AS b25024_002_e,
  NULLIF(json[7]::VARCHAR, '')::BIGINT  AS b25024_003_e,
  NULLIF(json[8]::VARCHAR, '')::BIGINT  AS b25024_004_e,
  NULLIF(json[9]::VARCHAR, '')::BIGINT  AS b25024_005_e,
  NULLIF(json[10]::VARCHAR, '')::BIGINT AS b25024_006_e,
  NULLIF(json[11]::VARCHAR, '')::BIGINT AS b25024_007_e,
  NULLIF(json[12]::VARCHAR, '')::BIGINT AS b25024_008_e,
  NULLIF(json[13]::VARCHAR, '')::BIGINT AS b25024_009_e,
  NULLIF(json[14]::VARCHAR, '')::BIGINT AS b25008_001_e,
  NULLIF(json[15]::VARCHAR, '')::BIGINT AS b25008_002_e,
  NULLIF(json[16]::VARCHAR, '')::BIGINT AS b25008_003_e,
  NULLIF(json[17]::VARCHAR, '')::BIGINT AS b19013_001_e,
  NULLIF(json[18]::VARCHAR, '')::BIGINT AS b25070_001_e,
  NULLIF(json[19]::VARCHAR, '')::BIGINT AS b25070_007_e,
  NULLIF(json[20]::VARCHAR, '')::BIGINT AS b25070_008_e,
  NULLIF(json[21]::VARCHAR, '')::BIGINT AS b25070_009_e,
  NULLIF(json[22]::VARCHAR, '')::BIGINT AS b25070_010_e,
  NULLIF(json[23]::VARCHAR, '')::BIGINT AS b25091_001_e,
  NULLIF(json[24]::VARCHAR, '')::BIGINT AS b25091_005_e,
  NULLIF(json[25]::VARCHAR, '')::BIGINT AS b25091_006_e,
  NULLIF(json[26]::VARCHAR, '')::BIGINT AS b25091_007_e,
  NULLIF(json[27]::VARCHAR, '')::BIGINT AS b25091_011_e,
  NULLIF(json[28]::VARCHAR, '')::BIGINT AS b25091_012_e,
  NULLIF(json[29]::VARCHAR, '')::BIGINT AS b25091_013_e,
  NULLIF(json[30]::VARCHAR, '')::BIGINT AS b03002_001_e,
  NULLIF(json[31]::VARCHAR, '')::BIGINT AS b03002_002_e,
  NULLIF(json[32]::VARCHAR, '')::BIGINT AS b03002_003_e,
  NULLIF(json[33]::VARCHAR, '')::BIGINT AS b03002_004_e,
  NULLIF(json[34]::VARCHAR, '')::BIGINT AS b03002_005_e,
  NULLIF(json[35]::VARCHAR, '')::BIGINT AS b03002_012_e,
  NULLIF(json[36]::VARCHAR, '')::BIGINT AS b15003_001_e,
  NULLIF(json[37]::VARCHAR, '')::BIGINT AS b15003_022_e,
  NULLIF(json[38]::VARCHAR, '')::BIGINT AS b15003_023_e,
  NULLIF(json[39]::VARCHAR, '')::BIGINT AS b15003_024_e,
  NULLIF(json[40]::VARCHAR, '')::BIGINT AS b15003_025_e
FROM numbered
WHERE rn > 1;  -- skip header row

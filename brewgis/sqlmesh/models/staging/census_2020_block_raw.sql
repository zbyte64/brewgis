MODEL (
  name duckdb.staging.census_2020_block_raw,
  kind VIEW,
  gateway duckdb,
  dialect duckdb
);

-- Census 2020 Decennial P.L. 94-171 block-level raw data — DuckDB reads
-- directly from Census API via httpfs.
--
-- The Census API returns JSON in the format: [[headers], [row1], [row2], ...].
-- Each row is a flat array of strings.  This model uses read_json_auto with
-- format='array' to parse the response, skips the header row, and maps
-- columns by position (DuckDB list indexing is 1-based).
--
-- Column positions:
--   [1] = P1_001N (total population)
--   [2] = H1_001N (total housing units)
--   [3] = state
--   [4] = county
--   [5] = tract
--   [6] = block
--
-- Variables (from SQLMesh @VAR macro — set in config.py):
--   @state_fips      — Two-digit state FIPS code (default '06')
--   @county_fips     — Three-digit county code; supports '*' for all counties
--   @census_api_key  — Census API key; empty string skips the &key= param
SET allow_asterisks_in_http_paths = true;

WITH api_response AS MATERIALIZED (
  SELECT *
  FROM read_json_auto(
    'https://api.census.gov/data/2020/dec/pl'
    || '?get=P1_001N,H1_001N'
    || '&for=block:*'
    || '&in=state:' || @state_fips || '+county:' || @county_fips || '+tract:*'
    || CASE WHEN @census_api_key <> '' THEN '&key=' || @census_api_key ELSE '' END,
    format = 'auto'
  )
),
numbered AS (
  SELECT
    ROW_NUMBER() OVER () AS rn,
    json
  FROM api_response
)
SELECT
  json[3]::VARCHAR || json[4]::VARCHAR || json[5]::VARCHAR || json[6]::VARCHAR AS geoid,
  NULLIF(json[1]::VARCHAR, '')::BIGINT AS total_population,
  NULLIF(json[2]::VARCHAR, '')::BIGINT AS total_housing_units,
  json[3]::VARCHAR AS state,
  json[4]::VARCHAR AS county
FROM numbered
WHERE rn > 1;  -- skip header row

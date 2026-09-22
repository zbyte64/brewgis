MODEL (
  name duckdb.@{region}.cbp_raw,
  kind VIEW,
  description 'DuckDB staging VIEW of County Business Patterns county employment from the Census API.',
  column_descriptions (
    year = 'CBP data year taken from the acs_year variable (2013 for sacog, 2022 for fresno).',
    emp = 'Total employment reported for the county-industry record (count).',
    naics_code = 'NAICS code from the API: 2017 when year is 2017 or later, 2012 when 2012 or later, else 2007.',
    state = 'Two-digit state FIPS code returned by the Census API.',
    county = 'Three-digit county FIPS code returned by the Census API.'
  ),
  gateway duckdb,
  dialect duckdb,
  blueprints @region_blueprints()
);

-- County Business Patterns raw data — DuckDB reads from Census API via httpfs.
--
-- The CBP API returns JSON in the format [[headers], [row1], [row2], ...].
-- This model uses read_json_auto with format='array' to parse the response,
-- skips the header row, and maps columns by position.
--
-- Columns: EMP (employment), NAICS2017 (NAICS code), state, county
-- The NAICS code uses 2017 vintage when year >= 2017, else 2007.
--
-- Variables (from SQLMesh blueprint columns; bare @refs resolve to the
-- region's blueprint value over the config default):
--   @acs_year      — CBP data year (sacog 2013, fresno 2022)
--   @county_fips   — Three-digit county code; supports '*' for all counties
--   @state_fips    — Two-digit state FIPS code (default '06')
--   @census_api_key  — Census API key; empty string skips the &key= param
SET allow_asterisks_in_http_paths = true;

WITH api_response AS MATERIALIZED (
  SELECT
    ROW_NUMBER() OVER () AS rn,
    json
  FROM read_json_auto(
    'https://api.census.gov/data/' || CAST(@acs_year AS VARCHAR) || '/cbp'
    || '?get=EMP,NAICS' || CASE WHEN CAST(@acs_year AS INTEGER) >= 2017 THEN '2017'
    WHEN CAST(@acs_year AS INTEGER) >= 2012 THEN '2012'
    ELSE '2007' END
    || '&for=county:*&in=state:' || @state_fips
    || CASE WHEN @county_fips <> '*' THEN '&for=county:' || @county_fips ELSE '' END
    || CASE WHEN @census_api_key <> '' THEN '&key=' || @census_api_key ELSE '' END,
    format = 'array'
  )
)
SELECT
  CAST(@acs_year AS INTEGER) AS year,
  NULLIF(json[1]::VARCHAR, '')::BIGINT AS emp,
  TRIM(json[2]::VARCHAR) AS naics_code,
  json[3]::VARCHAR AS state,
  json[4]::VARCHAR AS county
FROM api_response
WHERE rn > 1;  -- skip header row

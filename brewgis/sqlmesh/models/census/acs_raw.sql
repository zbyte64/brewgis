MODEL (
  name duckdb.@{region}.acs_raw,
  kind VIEW,
  description 'DuckDB staging VIEW of the Census ACS 5-year block group variables fetched live from the Census API via httpfs, one row per block group.',
  column_descriptions (
    year = 'ACS 5-year data year the API response was fetched for (@acs_year).',
    state = 'Two-digit state FIPS code returned by the API in field 41.',
    county = 'Three-digit county FIPS code returned by the API in field 42.',
    tract = 'Six-digit census tract code returned by the API in field 43.',
    block_group = 'Single-digit census block group code within the tract, API field 44.',
    b01001_001_e = 'ACS B01001_001E total population (people).',
    b25003_001_e = 'ACS B25003_001E total occupied housing units (households).',
    b25003_002_e = 'ACS B25003_002E owner-occupied housing units.',
    b25003_003_e = 'ACS B25003_003E renter-occupied housing units.',
    b25024_001_e = 'ACS B25024_001E total housing units.',
    b25024_002_e = 'ACS B25024_002E housing units in 1-unit detached structures.',
    b25024_003_e = 'ACS B25024_003E housing units in 1-unit attached structures.',
    b25024_004_e = 'ACS B25024_004E housing units in 2-unit structures.',
    b25024_005_e = 'ACS B25024_005E housing units in 3 or 4 unit structures.',
    b25024_006_e = 'ACS B25024_006E housing units in 5 to 9 unit structures.',
    b25024_007_e = 'ACS B25024_007E housing units in 10 to 19 unit structures.',
    b25024_008_e = 'ACS B25024_008E housing units in 20 to 49 unit structures.',
    b25024_009_e = 'ACS B25024_009E housing units in structures of 50 or more units.',
    b25008_001_e = 'ACS B25008_001E total population living in occupied housing units.',
    b25008_002_e = 'ACS B25008_002E population living in owner-occupied housing units.',
    b25008_003_e = 'ACS B25008_003E population living in renter-occupied housing units.',
    b19013_001_e = 'ACS B19013_001E median household income (dollars per year).',
    b25070_001_e = 'ACS B25070_001E renter households in the gross rent share of income universe.',
    b25070_007_e = 'ACS B25070_007E renter households paying 30.0-34.9 percent of income in gross rent.',
    b25070_008_e = 'ACS B25070_008E renter households paying 35.0-39.9 percent of income in gross rent.',
    b25070_009_e = 'ACS B25070_009E renter households paying 40.0-49.9 percent of income in gross rent.',
    b25070_010_e = 'ACS B25070_010E renter households paying 50.0 percent or more of income in gross rent.',
    b25091_001_e = 'ACS B25091_001E total owner-occupied units in the owner cost share of income universe.',
    b25091_005_e = 'ACS B25091_005E owners with a mortgage paying 30.0-34.9 percent of income in owner costs.',
    b25091_006_e = 'ACS B25091_006E owners with a mortgage paying 35.0-49.9 percent of income in owner costs.',
    b25091_007_e = 'ACS B25091_007E owners with a mortgage paying 50.0 percent or more of income in owner costs.',
    b25091_011_e = 'ACS B25091_011E owners without a mortgage paying 30.0-34.9 percent of income in owner costs.',
    b25091_012_e = 'ACS B25091_012E owners without a mortgage paying 35.0-49.9 percent of income in owner costs.',
    b25091_013_e = 'ACS B25091_013E owners without a mortgage paying 50.0 percent or more of income.',
    b03002_001_e = 'ACS B03002_001E total population in the Hispanic origin by race universe.',
    b03002_002_e = 'ACS B03002_002E population not Hispanic or Latino reporting White alone.',
    b03002_003_e = 'ACS B03002_003E population not Hispanic or Latino reporting Black or African American alone.',
    b03002_004_e = 'ACS B03002_004E population not Hispanic reporting American Indian and Alaska Native alone.',
    b03002_005_e = 'ACS B03002_005E population not Hispanic or Latino reporting Asian alone.',
    b03002_012_e = 'ACS B03002_012E population of Hispanic or Latino origin of any race.',
    b15003_001_e = 'ACS B15003_001E population 25 years and over in the educational attainment universe.',
    b15003_022_e = 'ACS B15003_022E population 25 and over holding a bachelors degree.',
    b15003_023_e = 'ACS B15003_023E population 25 and over holding a masters degree.',
    b15003_024_e = 'ACS B15003_024E population 25 and over holding a professional school degree.',
    b15003_025_e = 'ACS B15003_025E population 25 and over holding a doctorate degree.'
  ),
  gateway duckdb,
  dialect duckdb,
  blueprints @region_blueprints()
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
-- Variables are listed in the same order as ACS_TABLE_GROUPS in census_fetcher.py.
--
-- Variables (from SQLMesh blueprint columns; bare @refs resolve to the
-- region's blueprint value over the config default):
--   @acs_year      — ACS 5-year data year (sacog 2013, fresno 2022)
--   @state_fips      — Two-digit state FIPS code (default '06')
--   @county_fips   — Three-digit county code(s); supports '*' for all counties
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

MODEL (
  name duckdb.@{region}.pdb_raw,
  kind VIEW,
  gateway duckdb,
  dialect duckdb,
  blueprints (
    (region := sacog,  county_fips := '067,005,017,061'),
    (region := fresno, county_fips := '019')
  )
);

-- Census Planning Database (PDB) raw data — DuckDB reads directly from Census API via httpfs.
--
-- The Census API returns JSON in the format: [[headers], [row1], [row2], ...].
-- Each row is a flat array of strings.  This model uses read_json_auto with
-- format='array' to parse the response, skips the header row, and maps
-- columns by position (DuckDB list indexing is 1-based).
--
-- Columns 1-11 are PDB variables (in get= parameter order).
-- Columns 12-13 are geography (state, county) from the in= clause.
-- Column 14 is block group from the for= clause.
--
-- PDB is ACS 2018-2022 vintage (data_year = 2024).

SET allow_asterisks_in_http_paths = true;

WITH api_response AS MATERIALIZED (
  SELECT *
  FROM read_json_auto(
    'https://api.census.gov/data/2024/pdb/blockgroup'
    || '?get=GIDBG'
    || ',Tot_Vacant_Units_ACS_18_22'
    || ',Tot_Housing_Units_ACS_18_22'
    || ',Tot_Occp_Units_ACS_18_22'
    || ',Tot_GQ_CEN_2020'
    || ',Inst_GQ_CEN_2020'
    || ',Non_Inst_GQ_CEN_2020'
    || ',Low_Response_Score'
    || ',pct_Renter_Occp_HU_ACS_18_22'
    || ',pct_Prs_Blw_Pov_Lev_ACS_18_22'
    || ',Tot_Population_ACS_18_22'
    || '&for=block+group:*'
    || '&in=state:' || @state_fips
    || '+county:' || @county_fips
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
  json[1]::VARCHAR  AS gidbg,
  NULLIF(json[2]::VARCHAR, '')::BIGINT  AS tot_vacant_units_acs_18_22,
  NULLIF(json[3]::VARCHAR, '')::BIGINT  AS tot_housing_units_acs_18_22,
  NULLIF(json[4]::VARCHAR, '')::BIGINT  AS tot_occp_units_acs_18_22,
  NULLIF(json[5]::VARCHAR, '')::BIGINT  AS tot_gq_cen_2020,
  NULLIF(json[6]::VARCHAR, '')::BIGINT  AS inst_gq_cen_2020,
  NULLIF(json[7]::VARCHAR, '')::BIGINT  AS non_inst_gq_cen_2020,
  NULLIF(json[8]::VARCHAR, '')::DOUBLE AS low_response_score,
  NULLIF(json[9]::VARCHAR, '')::DOUBLE  AS pct_renter_occp_hu_acs_18_22,
  NULLIF(json[10]::VARCHAR, '')::DOUBLE AS pct_prs_blw_pov_lev_acs_18_22,
  NULLIF(json[11]::VARCHAR, '')::BIGINT AS tot_population_acs_18_22,
  json[12]::VARCHAR AS state,
  json[13]::VARCHAR AS county,
  2024 AS data_year
FROM numbered
WHERE rn > 1;  -- skip header row

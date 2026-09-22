MODEL (
  name brewgis.@{region}.acs_bridge,
  kind FULL,
  description 'PostGIS bridge that materializes the DuckDB acs_raw ACS 5-year block group VIEW (Census API source) into a queryable table, one row per block group.',
  column_descriptions (
    year = 'ACS 5-year data year the block group record was fetched for.',
    state = 'Two-digit state FIPS code of the block group.',
    county = 'Three-digit county FIPS code of the block group.',
    tract = 'Six-digit census tract code of the block group.',
    block_group = 'Single-digit census block group code within the tract.',
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
  blueprints @region_blueprints()
);

-- ACS Raw Bridge — materializes the DuckDB VIEW (which reads from Census API)
-- into a PostGIS-accessible table so downstream PostGIS models can reference
-- it via cross-gateway reads.
--
-- Replaces the public.acs_raw table previously created by the dlt census pipeline.
-- All columns match the dlt staging schema in external_models/dlt_staging.yaml.

SELECT * FROM duckdb.@{region}.acs_raw;

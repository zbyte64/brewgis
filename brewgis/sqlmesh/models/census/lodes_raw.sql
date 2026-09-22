MODEL (
  name duckdb.@{region}.lodes_raw,
  kind VIEW,
  description 'DuckDB staging VIEW of the gzipped LEHD LODES WAC CSV for the region state and year read from the CES FTP via httpfs, one row per census block work area.',
  column_descriptions (
    year = 'LEHD LODES release year the WAC file covers (@lodes_year).',
    w_geocode = '15-digit census block GEOID of the workplace the jobs are reported for.',
    c000 = 'LODES C000 total jobs in the block.',
    cns01 = 'LODES WAC segment CNS01 jobs in the block: goods producing (NAICS 11, 21 and 23).',
    cns02 = 'LODES WAC segment CNS02 jobs in the block: manufacturing.',
    cns03 = 'LODES WAC segment CNS03 jobs in the block: trade, transport and utilities.',
    cns04 = 'LODES WAC segment CNS04 jobs in the block: information.',
    cns05 = 'LODES WAC segment CNS05 jobs in the block: finance and insurance.',
    cns06 = 'LODES WAC segment CNS06 jobs in the block: real estate.',
    cns07 = 'LODES WAC segment CNS07 jobs in the block: professional services.',
    cns08 = 'LODES WAC segment CNS08 jobs in the block: management.',
    cns09 = 'LODES WAC segment CNS09 jobs in the block: admin and support.',
    cns10 = 'LODES WAC segment CNS10 jobs in the block: educational services.',
    cns11 = 'LODES WAC segment CNS11 jobs in the block: health care.',
    cns12 = 'LODES WAC segment CNS12 jobs in the block: arts and entertainment.',
    cns13 = 'LODES WAC segment CNS13 jobs in the block: accommodation and food.',
    cns14 = 'LODES WAC segment CNS14 jobs in the block: other services.',
    cns15 = 'LODES WAC segment CNS15 jobs in the block: public administration.',
    cns16 = 'LODES WAC segment CNS16 jobs in the block: unclassified.',
    cns17 = 'LODES WAC segment CNS17 jobs in the block: armed forces.',
    cns18 = 'LODES WAC segment CNS18 jobs in the block: federal government.',
    cns19 = 'LODES WAC segment CNS19 jobs in the block: state government.',
    cns20 = 'LODES WAC segment CNS20 jobs in the block: local government.'
  ),
  gateway duckdb,
  dialect duckdb,
  blueprints @region_blueprints()
);

-- LEHD LODES WAC raw data — DuckDB reads gzipped CSV from CES FTP via httpfs.
--
-- The LEHD API provides per-state gzipped CSV files at:
--   https://lehd.ces.census.gov/data/lodes/LODES8/{state_abbr}/wac/
--   {state_abbr}_wac_S000_JT00_{year}.csv.gz
--
-- This model constructs the URL using a Jinja macro at render time, avoiding
-- DuckDB's restriction that read_csv_auto only accepts literal file paths
-- (not column references).
--
-- Variables (from SQLMesh blueprint columns, read via blueprint_var in the
-- Jinja body; resolve to the region's blueprint value over the config default):
--   lodes_year    — LEHD LODES release year (sacog 2008, fresno 2021)
--   county_fips   — Three-digit county code for row-level filtering
--   state_fips    — Two-digit state FIPS code (default '06')

JINJA_QUERY_BEGIN;
{% set fips_to_abbr = {
    '01': 'al', '02': 'ak', '04': 'az', '05': 'ar', '06': 'ca', '08': 'co',
    '09': 'ct', '10': 'de', '11': 'dc', '12': 'fl', '13': 'ga', '15': 'hi',
    '16': 'id', '17': 'il', '18': 'in', '19': 'ia', '20': 'ks', '21': 'ky',
    '22': 'la', '23': 'me', '24': 'md', '25': 'ma', '26': 'mi', '27': 'mn',
    '28': 'ms', '29': 'mo', '30': 'mt', '31': 'ne', '32': 'nv', '33': 'nh',
    '34': 'nj', '35': 'nm', '36': 'ny', '37': 'nc', '38': 'nd', '39': 'oh',
    '40': 'ok', '41': 'or', '42': 'pa', '44': 'ri', '45': 'sc', '46': 'sd',
    '47': 'tn', '48': 'tx', '49': 'ut', '50': 'vt', '51': 'va', '53': 'wa',
    '54': 'wv', '55': 'wi', '56': 'wy', '60': 'as', '66': 'gu', '69': 'mp',
    '72': 'pr', '74': 'um', '78': 'vi',
} %}
{% set state_fips_val = var('state_fips') %}
{% set state_abbr = fips_to_abbr.get(state_fips_val, '') %}
{% set lodes_year_val = blueprint_var('lodes_year') %}
{% set county_fips_val = blueprint_var('county_fips') %}

SELECT
  CAST({{ lodes_year_val }} AS INTEGER) AS year,
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
FROM read_csv_auto(
    'https://lehd.ces.census.gov/data/lodes/LODES8/{{ state_abbr }}/wac/{{ state_abbr }}_wac_S000_JT00_{{ lodes_year_val }}.csv.gz',
    header = true,
    delim = ',',
    all_varchar = true
)
WHERE EXISTS (
  SELECT 1
  FROM (SELECT unnest(string_split({{ county_fips_val }}, ',')) AS c) codes
  WHERE LEFT(w_geocode, 5) = CONCAT('{{ state_fips_val }}', codes.c)
);
JINJA_END;

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
-- This model constructs the URL using a Jinja macro at render time, avoiding
-- DuckDB's restriction that read_csv_auto only accepts literal file paths
-- (not column references).
--
-- Variables (set in config.py):
--   lodes_year    — LEHD LODES release year (default 2008)
--   state_fips    — Two-digit state FIPS code (default '06')
--   county_fips   — Three-digit county code for row-level filtering

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
{% set lodes_year_val = var('lodes_year') %}
{% set county_fips_val = var('county_fips') %}

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
WHERE LEFT(w_geocode, 5) = CONCAT('{{ state_fips_val }}', '{{ county_fips_val }}');
JINJA_END;

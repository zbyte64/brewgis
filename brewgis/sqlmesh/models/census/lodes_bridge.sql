MODEL (
  name brewgis.@{region}.lodes_raw,
  kind FULL,
  description 'PostGIS bridge that materializes the DuckDB lodes_raw LODES WAC VIEW (CES FTP CSV source) into a queryable table, one row per census block work area.',
  column_descriptions (
    year = 'LEHD LODES release year of the record.',
    w_geocode = '15-digit census block GEOID of the workplace the jobs are reported for.',
    c000 = 'LODES C000 total jobs in the block.',
    cns01 = 'LODES WAC segment CNS01 jobs in the block: agriculture, forestry, fishing and hunting (NAICS 11).',
    cns02 = 'LODES WAC segment CNS02 jobs in the block: mining, quarrying, and oil and gas extraction (NAICS 21).',
    cns03 = 'LODES WAC segment CNS03 jobs in the block: utilities (NAICS 22).',
    cns04 = 'LODES WAC segment CNS04 jobs in the block: construction (NAICS 23).',
    cns05 = 'LODES WAC segment CNS05 jobs in the block: manufacturing (NAICS 31-33).',
    cns06 = 'LODES WAC segment CNS06 jobs in the block: wholesale trade (NAICS 42).',
    cns07 = 'LODES WAC segment CNS07 jobs in the block: retail trade (NAICS 44-45).',
    cns08 = 'LODES WAC segment CNS08 jobs in the block: transportation and warehousing (NAICS 48-49).',
    cns09 = 'LODES WAC segment CNS09 jobs in the block: information (NAICS 51).',
    cns10 = 'LODES WAC segment CNS10 jobs in the block: finance and insurance (NAICS 52).',
    cns11 = 'LODES WAC segment CNS11 jobs in the block: real estate and rental and leasing (NAICS 53).',
    cns12 = 'LODES WAC segment CNS12 jobs in the block: professional, scientific, and technical services (NAICS 54).',
    cns13 = 'LODES WAC segment CNS13 jobs in the block: management of companies and enterprises (NAICS 55).',
    cns14 = 'LODES WAC segment CNS14 jobs in the block: administrative and support and waste management (NAICS 56).',
    cns15 = 'LODES WAC segment CNS15 jobs in the block: educational services (NAICS 61).',
    cns16 = 'LODES WAC segment CNS16 jobs in the block: health care and social assistance (NAICS 62).',
    cns17 = 'LODES WAC segment CNS17 jobs in the block: arts, entertainment, and recreation (NAICS 71).',
    cns18 = 'LODES WAC segment CNS18 jobs in the block: accommodation and food services (NAICS 72).',
    cns19 = 'LODES WAC segment CNS19 jobs in the block: other services except public administration (NAICS 81).',
    cns20 = 'LODES WAC segment CNS20 jobs in the block: public administration (NAICS 92).'
  ),
  gateway duckdb,
  blueprints @region_blueprints()
);

-- LODES Raw Bridge — materializes the DuckDB VIEW (which reads gzipped CSV
-- from CES FTP via httpfs) into a PostGIS-accessible table so downstream
-- PostGIS models can reference it via cross-gateway reads.
--
-- Replaces the public.lodes_raw table previously created by the dlt lehd pipeline.
-- All columns match the dlt staging schema in external_models/dlt_staging.yaml.

SELECT * FROM duckdb.@{region}.lodes_raw;

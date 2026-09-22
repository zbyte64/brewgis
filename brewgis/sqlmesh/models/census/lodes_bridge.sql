MODEL (
  name brewgis.@{region}.lodes_raw,
  kind FULL,
  description 'PostGIS bridge that materializes the DuckDB lodes_raw LODES WAC VIEW (CES FTP CSV source) into a queryable table, one row per census block work area.',
  column_descriptions (
    year = 'LEHD LODES release year of the record.',
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
  blueprints @region_blueprints()
);

-- LODES Raw Bridge — materializes the DuckDB VIEW (which reads gzipped CSV
-- from CES FTP via httpfs) into a PostGIS-accessible table so downstream
-- PostGIS models can reference it via cross-gateway reads.
--
-- Replaces the public.lodes_raw table previously created by the dlt lehd pipeline.
-- All columns match the dlt staging schema in external_models/dlt_staging.yaml.

SELECT * FROM duckdb.@{region}.lodes_raw;

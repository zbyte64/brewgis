MODEL (
  name brewgis.@{region}.census_2020_block_raw,
  kind FULL,
  description 'PostGIS bridge materializing the census_2020_block_raw DuckDB VIEW, one census block per row.',
  column_descriptions (
    geoid = 'Census block GEOID from the API state, county, tract and block codes (15-digit FIPS).',
    total_population = 'Total population of the block from the PL 94-171 P1_001N field (people).',
    total_housing_units = 'Total housing units in the block from the PL 94-171 H1_001N field (housing units).',
    state = 'Two-digit state FIPS code returned by the Census API.',
    county = 'Three-digit county FIPS code returned by the Census API.'
  ),
  gateway duckdb,
  blueprints @region_blueprints()
);

-- Census 2020 Block Raw Bridge — materializes the DuckDB VIEW (which reads
-- from Census API) into a PostGIS-accessible table so downstream PostGIS
-- models can reference it via cross-gateway reads.
--
-- Replaces the public.census_2020_block_raw table previously created by the
-- dlt census_2020 pipeline.

SELECT * FROM duckdb.@{region}.census_2020_block_raw;

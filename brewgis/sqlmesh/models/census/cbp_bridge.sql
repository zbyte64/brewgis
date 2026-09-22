MODEL (
  name brewgis.@{region}.cbp_raw,
  kind FULL,
  description 'PostGIS bridge materializing the DuckDB staging VIEW of County Business Patterns employment.',
  column_descriptions (
    year = 'CBP data year taken from the acs_year variable (2013 for sacog, 2022 for fresno).',
    emp = 'Total employment reported for the county-industry record (count).',
    naics_code = 'NAICS code from the API: 2017 when year is 2017 or later, 2012 when 2012 or later, else 2007.',
    state = 'Two-digit state FIPS code returned by the Census API.',
    county = 'Three-digit county FIPS code returned by the Census API.'
  ),
  gateway duckdb,
  blueprints @region_blueprints()
);

-- CBP Raw Bridge — materializes the DuckDB VIEW (which reads from Census CBP API)
-- into a PostGIS-accessible table so downstream PostGIS models can reference it.

SELECT * FROM duckdb.@{region}.cbp_raw;

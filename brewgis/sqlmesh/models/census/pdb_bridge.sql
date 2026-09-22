MODEL (
  name brewgis.@{region}.pdb_bridge,
  kind FULL,
  description 'PostGIS bridge that materializes the DuckDB pdb_raw Census Planning Database block group VIEW into a queryable table, one row per block group.',
  column_descriptions (
    gidbg = 'Census block group GEOID (12-digit state+county+tract+block group FIPS) of the record.',
    tot_vacant_units_acs_18_22 = 'Total vacant housing units (ACS 2018-2022 estimate).',
    tot_housing_units_acs_18_22 = 'Total housing units (ACS 2018-2022 estimate).',
    tot_occp_units_acs_18_22 = 'Total occupied housing units (ACS 2018-2022 estimate).',
    tot_gq_cen_2020 = 'Total group quarters population from the 2020 Census enumeration.',
    inst_gq_cen_2020 = 'Institutional group quarters population from the 2020 Census enumeration.',
    non_inst_gq_cen_2020 = 'Non-institutional group quarters population from the 2020 Census enumeration.',
    low_response_score = 'PDB low response score for the block group, a predicted self-response shortfall (percent).',
    pct_renter_occp_hu_acs_18_22 = 'Renter-occupied housing units as a percent of occupied units (ACS 2018-2022).',
    pct_prs_blw_pov_lev_acs_18_22 = 'Persons below the poverty level as a percent of the universe (ACS 2018-2022).',
    tot_population_acs_18_22 = 'Total population of the block group (ACS 2018-2022 estimate).',
    state = 'Two-digit state FIPS code of the block group.',
    county = 'Three-digit county FIPS code of the block group.',
    data_year = 'PDB vintage year (2024) the record belongs to.'
  ),
  gateway duckdb,
  blueprints @region_blueprints()
);

-- PDB Raw Bridge — materializes the DuckDB VIEW (which reads from Census API)
-- into a PostGIS-accessible table so downstream PostGIS models can reference
-- it via cross-gateway reads.
--
-- Replaces the public.pdb_raw table previously created by the dlt pdb pipeline.
-- All columns match the dlt staging schema in pdb.py:dlt.resource(columns=...).

SELECT * FROM duckdb.@{region}.pdb_raw;

MODEL (
  name brewgis.seeds.test_acs_block_group,
  kind SEED (
    path '../../seeds/test_acs_block_group.csv'
  ),
  description 'Test fixture: 3 synthetic ACS block groups for the test_stage_acs_bg staging view unit test.',
  column_descriptions (
    geoid = 'Census block group GEOID (12-digit FIPS).',
    pop = 'Total population of the block group (people).',
    hh = 'Household count of the block group.',
    du = 'Dwelling unit count of the block group.',
    du_detsf = 'Detached single-family dwelling units in the block group.',
    du_detsf_sl = 'Detached single-family small-lot dwelling units in the block group.',
    du_detsf_ll = 'Detached single-family large-lot dwelling units in the block group.',
    du_attsf = 'Attached single-family dwelling units in the block group.',
    du_mf = 'Multi-family dwelling units in the block group.',
    du_mf2to4 = 'Multi-family 2 to 4 unit dwelling units in the block group.',
    du_mf5p = 'Multi-family 5 or more unit dwelling units in the block group.',
    median_income = 'Median household income of the block group ($ per year).',
    rent_burden_pct = 'Share of households paying over 30 percent of income on rent (% as 0-100).',
    pct_minority = 'Share of the population that is people of color (% as 0-100).',
    pct_college_educated = 'Share of the population with a college degree (% as 0-100).',
    cost_burden_pct = 'Share of households that are cost-burdened (% as 0-100).',
    geometry = 'Block group boundary polygon in EPSG:4326 (WGS 84).'
  ),
  columns (
    geoid TEXT,
    pop DOUBLE PRECISION,
    hh DOUBLE PRECISION,
    du DOUBLE PRECISION,
    du_detsf DOUBLE PRECISION,
    du_detsf_sl DOUBLE PRECISION,
    du_detsf_ll DOUBLE PRECISION,
    du_attsf DOUBLE PRECISION,
    du_mf DOUBLE PRECISION,
    du_mf2to4 DOUBLE PRECISION,
    du_mf5p DOUBLE PRECISION,
    median_income DOUBLE PRECISION,
    rent_burden_pct DOUBLE PRECISION,
    pct_minority DOUBLE PRECISION,
    pct_college_educated DOUBLE PRECISION,
    cost_burden_pct DOUBLE PRECISION,
    geometry geometry(Geometry,4326)
  )
);

MODEL (
  name brewgis.seeds.test_acs_block_group,
  kind SEED (
    path '../../seeds/test_acs_block_group.csv'
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

MODEL (
  name brewgis.seeds.test_acs_block_group,
  kind SEED (
    path '../../seeds/test_acs_block_group.csv'
  ),
  columns (
    geoid TEXT,
    pop TEXT,
    hh TEXT,
    du TEXT,
    du_detsf TEXT,
    du_detsf_sl TEXT,
    du_detsf_ll TEXT,
    du_attsf TEXT,
    du_mf TEXT,
    du_mf2to4 TEXT,
    du_mf5p TEXT,
    median_income TEXT,
    rent_burden_pct TEXT,
    pct_minority TEXT,
    pct_college_educated TEXT,
    cost_burden_pct TEXT,
    geometry geometry(Geometry,4326)
  )
);

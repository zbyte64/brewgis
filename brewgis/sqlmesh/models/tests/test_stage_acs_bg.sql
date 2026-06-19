MODEL (
  name brewgis.tests.test_stage_acs_bg,
  kind VIEW,
  audits (
    not_null(columns := (geoid))
  )
);

-- Test staging model: produces output matching acs_block_group schema
-- from the test_acs_block_group seed data.

SELECT
    geoid,
    pop::double precision AS pop,
    hh::double precision AS hh,
    du::double precision AS du,
    du_detsf::double precision AS du_detsf,
    du_detsf_sl::double precision AS du_detsf_sl,
    du_detsf_ll::double precision AS du_detsf_ll,
    du_attsf::double precision AS du_attsf,
    du_mf::double precision AS du_mf,
    du_mf2to4::double precision AS du_mf2to4,
    du_mf5p::double precision AS du_mf5p,
    median_income::double precision AS median_income,
    rent_burden_pct::double precision AS rent_burden_pct,
    pct_minority::double precision AS pct_minority,
    pct_college_educated::double precision AS pct_college_educated,
    cost_burden_pct::double precision AS cost_burden_pct,
    geometry
FROM brewgis.seeds.test_acs_block_group;

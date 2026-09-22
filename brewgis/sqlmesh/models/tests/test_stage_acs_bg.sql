MODEL (
  name brewgis.tests.test_stage_acs_bg,
  kind VIEW,
  description 'Test fixture: staging VIEW matching the acs_block_group schema from the test_acs_block_group seed.',
  column_descriptions (
    geoid = 'Census block group GEOID the ACS demographics belong to.',
    pop = 'Total population of the block group (people).',
    hh = 'Households in the block group (count).',
    du = 'Total housing units in the block group (count).',
    du_detsf = 'Detached single-family dwelling units (count).',
    du_detsf_sl = 'Detached single-family small lot dwelling units (count).',
    du_detsf_ll = 'Detached single-family large lot dwelling units (count).',
    du_attsf = 'Attached single-family dwelling units (count).',
    du_mf = 'Multi-family dwelling units (count).',
    du_mf2to4 = 'Multi-family 2 to 4 unit dwelling units (count).',
    du_mf5p = 'Multi-family 5 plus unit dwelling units (count).',
    median_income = 'Median household income of the block group ($ per year).',
    rent_burden_pct = 'Share of households paying over 30 percent of income on rent (percent).',
    pct_minority = 'Share of the block group population that is people of color (percent).',
    pct_college_educated = 'Share of the block group population with a college education (percent).',
    cost_burden_pct = 'Share of households that are cost burdened (percent).',
    geometry = 'Block group geometry from the test seed (EPSG:4326).'
  ),
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

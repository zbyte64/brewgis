MODEL (
  name brewgis.@{region}.pdb_block_group,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (geoid, data_year),
    batch_size 100000
  ),
  description 'Block group demographics from the Census Planning Database joined to TIGER/Line block group geometry, with the rates rescaled to 0-1 fractions, one row per block group.',
  column_descriptions (
    geoid = '12-digit block group GEOID (state+county+tract+block group FIPS) from the PDB GIDBG field.',
    geometry = 'Block group polygon (EPSG:4326, multipolygon) from TIGER/Line vintage @bg_vintage.',
    data_year = 'PDB vintage date (2024-01-01) the block group record belongs to.',
    vacancy_rate = 'Vacant housing units divided by total housing units, clamped to the 0-1 range (fraction).',
    group_quarters_pop = 'Group quarters population from the 2020 Census enumeration (people).',
    low_response_score = 'PDB low response score divided by 100 so it reads as a 0-1 fraction, NULL when absent.',
    renter_occupied_pct = 'Renter-occupied share of occupied units, divided by 100 to a 0-1 fraction.',
    below_poverty_pct = 'Share of persons below the poverty level divided by 100 to a 0-1 fraction, NULL when absent.'
  ),
  audits (
    not_null(columns := (geoid, data_year)),
    assert_pdb_block_group_coverage
  ),
  blueprints @region_blueprints()
);

-- Census Planning Database (PDB) → Block Group Demographics Table
--
-- Joins pdb_raw staging data with TIGER/Line block group geometry
-- and computes derived demographic columns (vacancy rate, group quarters
-- population, low response score, renter %, below poverty %).
--
-- PDB is ACS 2018-2022 vintage (data_year = 2024), so its block groups are 2020
-- TIGER geography and bg_vintage (blueprint, per region) must name a TIGER vintage
-- that carries them. Measured 2026-09-20: the fresno source holds 637 block groups
-- for county 019, and the former global '2013' default matched only 463 of them,
-- dropping 174 block groups — which cover 52,382 canvas parcels — from every
-- PDB-derived column. assert_pdb_block_group_coverage fails if this model's output
-- is missing a block group the source provides.

WITH raw_derived AS (
    SELECT
        p.gidbg AS geoid,
        ST_Multi(tbg.wgs84_geometry) AS geometry,
        -- Housing vacancy
        COALESCE(p.tot_vacant_units_acs_18_22, 0)::numeric AS vacant_units,
        COALESCE(p.tot_housing_units_acs_18_22, 0)::numeric AS housing_units,
        -- Occupied units
        COALESCE(p.tot_occp_units_acs_18_22, 0)::numeric AS occupied_units,
        -- Group quarters population (2020 Census enumeration, not ACS estimate)
        COALESCE(p.tot_gq_cen_2020, 0)::numeric AS group_quarters_pop,
        -- Low response score (predicted non-self-response %)
        p.low_response_score::double precision AS low_response_score_raw,
        -- Renter-occupied %
        p.pct_renter_occp_hu_acs_18_22::double precision AS pct_renter_occp_raw,
        -- Below poverty %
        p.pct_prs_blw_pov_lev_acs_18_22::double precision AS pct_below_poverty_raw
    FROM brewgis.@{region}.pdb_bridge p
    JOIN brewgis.census.tiger_block_groups tbg
        ON p.gidbg = tbg.geoid
        AND tbg.vintage = @bg_vintage
    WHERE p.state = @state_fips
      AND p.county = ANY(STRING_TO_ARRAY(@county_fips, ','))
),
derived_rates AS (
    SELECT
        geoid,
        geometry,
        -- Vacancy rate = vacant / total housing units (fraction, 0-1)
        CASE WHEN housing_units > 0
            THEN LEAST(1.0, GREATEST(0.0, vacant_units / NULLIF(housing_units, 0)))
            ELSE 0 END AS vacancy_rate,
        group_quarters_pop,
        -- Low response score: PDB gives as percent, convert to fraction
        CASE WHEN low_response_score_raw IS NOT NULL
            THEN LEAST(1.0, GREATEST(0.0, low_response_score_raw / 100.0))
            ELSE NULL END AS low_response_score,
        -- Renter-occupied %: PDB gives as percent, convert to fraction
        CASE WHEN pct_renter_occp_raw IS NOT NULL
            THEN LEAST(1.0, GREATEST(0.0, pct_renter_occp_raw / 100.0))
            ELSE NULL END AS renter_occupied_pct,
        -- Below poverty %: PDB gives as percent, convert to fraction
        CASE WHEN pct_below_poverty_raw IS NOT NULL
            THEN LEAST(1.0, GREATEST(0.0, pct_below_poverty_raw / 100.0))
            ELSE NULL END AS below_poverty_pct
    FROM raw_derived
)
SELECT
    geoid,
    geometry,
    make_date(2024, 1, 1) AS data_year,
    vacancy_rate,
    group_quarters_pop,
    low_response_score,
    renter_occupied_pct,
    below_poverty_pct
FROM derived_rates;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_pdb_block_group_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_pdb_block_group_geoid_')
  ON @this_model USING btree (geoid);

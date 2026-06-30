MODEL (
  name brewgis.staging.pdb_block_group,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (geoid, data_year),
    batch_size 100000
  ),
  audits (
    not_null(columns := (geoid, data_year))
  )
);

-- Census Planning Database (PDB) → Block Group Demographics Table
--
-- Joins pdb_raw staging data with TIGER/Line block group geometry
-- and computes derived demographic columns (vacancy rate, group quarters
-- population, low response score, renter %, below poverty %).
--
-- PDB is ACS 2018-2022 vintage (data_year = 2024).

WITH raw_derived AS (
    SELECT
        p.gidbg AS geoid,
        ST_Multi(tbg.geometry) AS geometry,
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
    FROM public.pdb_raw p
    JOIN public.tiger_block_groups tbg
        ON p.gidbg = tbg.geoid
        AND tbg.vintage = @tiger_bg_vintage
    WHERE p.state = '06'
      AND p.county = '067'
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
  CREATE INDEX IF NOT EXISTS idx_pdb_block_group_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_pdb_block_group_geoid_@snapshot_hash
  ON @this_model USING btree (geoid);

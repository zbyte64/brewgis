MODEL (
  name brewgis.staging.acs_block_group,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (geoid, data_year),
    batch_size 100000
  ),
  audits (
    not_null(columns := (geoid, data_year))
  )
);

-- Census ACS → Block Group Demographics Table
--
-- Joins acs_raw staging data with TIGER/Line block group geometry,
-- computes derived demographic columns, splits DU sub-types using
-- fixed ratios and a density-calibrated sigmoid for single-family lots.
--
-- Parameters (from dbt vars, with defaults):
--   year: 2022
--   state_fips: '06'
--   detsf_sl_ratio: 0.40 (fallback small-lot ratio when geometry unavailable)
--   sl_density_threshold: 8.0 (density threshold for small-lot sigmoid)
--   k_steepness: 0.5 (sigmoid steepness)
--   tiger_bg_vintage: '2013'

WITH raw_derived AS (
    SELECT
        a.state || a.county || a.tract || a."block_group" AS geoid,
        ST_Multi(tbg.geometry) AS geometry,
        COALESCE(a.b01001_001_e, 0)::numeric AS pop,
        COALESCE(a.b25003_001_e, 0)::numeric AS hh,
        COALESCE(a.b25024_001_e, 0)::numeric AS du,
        -- DU types
        COALESCE(a.b25024_002_e, 0)::numeric AS du_detsf,
        COALESCE(a.b25024_003_e, 0)::numeric AS du_attsf,
        COALESCE(a.b25024_004_e, 0)::numeric AS du_2,
        COALESCE(a.b25024_005_e, 0)::numeric AS du_3_4,
        COALESCE(a.b25024_006_e, 0)::numeric AS du_5_9,
        (COALESCE(a.b25024_007_e, 0) + COALESCE(a.b25024_008_e, 0)
            + COALESCE(a.b25024_009_e, 0))::numeric AS du_10p,
        -- Tenure
        COALESCE(a.b25003_002_e, 0)::numeric AS owner_occupied,
        COALESCE(a.b25003_003_e, 0)::numeric AS renter_occupied,
        -- Income
        COALESCE(a.b19013_001_e, 0)::numeric AS median_income,
        -- Rent burden
        COALESCE(a.b25070_001_e, 0)::numeric AS rent_total,
        (COALESCE(a.b25070_007_e, 0) + COALESCE(a.b25070_008_e, 0)
            + COALESCE(a.b25070_009_e, 0) + COALESCE(a.b25070_010_e, 0))::numeric AS renter_cost_burdened,
        -- Owner cost burden
        (COALESCE(a.b25091_005_e, 0) + COALESCE(a.b25091_006_e, 0)
            + COALESCE(a.b25091_007_e, 0) + COALESCE(a.b25091_011_e, 0)
            + COALESCE(a.b25091_012_e, 0) + COALESCE(a.b25091_013_e, 0))::numeric AS owner_cost_burdened,
        -- Demographics
        COALESCE(a.b03002_001_e, 0)::numeric AS total_population,
        COALESCE(a.b03002_002_e, 0)::numeric AS white_alone_pop,
        -- Education
        COALESCE(a.b15003_001_e, 0)::numeric AS edu_total,
        (COALESCE(a.b15003_022_e, 0) + COALESCE(a.b15003_023_e, 0)
            + COALESCE(a.b15003_024_e, 0) + COALESCE(a.b15003_025_e, 0))::numeric AS college_educated
    FROM public.acs_raw a
    JOIN public.tiger_block_groups tbg
        ON tbg.geoid = a.state || a.county || a.tract || a."block_group"
        AND tbg.vintage = @tiger_bg_vintage
    WHERE a.year = @acs_year
      AND a.state = @state_fips
),
derived_with_pcts AS (
    SELECT
        *,
        -- Safe percentages
        CASE WHEN rent_total > 0
            THEN ROUND(renter_cost_burdened / NULLIF(rent_total, 0) * 100.0, 2)
            ELSE 0 END AS rent_burden_pct,
        CASE WHEN hh > 0
            THEN ROUND((owner_cost_burdened + renter_cost_burdened) / NULLIF(hh, 0) * 100.0, 2)
            ELSE 0 END AS cost_burden_pct,
        CASE WHEN total_population > 0
            THEN ROUND((total_population - white_alone_pop) / NULLIF(total_population, 0) * 100.0, 2)
            ELSE 0 END AS pct_minority,
        CASE WHEN edu_total > 0
            THEN ROUND(college_educated / NULLIF(edu_total, 0) * 100.0, 2)
            ELSE 0 END AS pct_college_educated,
        -- DU sub-type splits (direct from ACS B25024 cells)
        ROUND(du_2 + du_3_4, 1) AS du_mf2to4,
        ROUND(du_5_9 + du_10p, 1) AS du_mf5p,
        -- Density-calibrated single-family lot split
        CASE
            WHEN du_detsf > 0 AND geometry IS NOT NULL AND ST_IsValid(geometry)
            THEN LEAST(1.0, GREATEST(0.0,
                1.0 / (1.0 + EXP(-0.5 * (
                    (du_detsf / NULLIF(ST_Area(ST_Transform(geometry, 6933)) / 4046.86, 0))
                    - 8.0
                )))
            ))
            ELSE 0.40
        END AS sl_ratio
    FROM raw_derived
)
SELECT
    geoid,
    geometry,
    make_date(@acs_year::int, 1, 1) AS data_year,
    pop,
    hh,
    du,
    ROUND(du_detsf::numeric, 1) AS du_detsf,
    du_attsf,
    du_mf2to4,
    du_mf5p,
    ROUND((du_mf2to4 + du_mf5p)::numeric, 1) AS du_mf,
    ROUND((du_detsf * sl_ratio)::numeric, 1) AS du_detsf_sl,
    ROUND((du_detsf * (1 - sl_ratio))::numeric, 1) AS du_detsf_ll,
    owner_occupied,
    renter_occupied,
    median_income,
    rent_burden_pct,
    cost_burden_pct,
    total_population,
    pct_minority,
    pct_college_educated
FROM derived_with_pcts;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_acs_block_group_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_acs_block_group_geoid_@snapshot_hash
  ON @this_model USING btree (geoid);

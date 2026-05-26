{#
    Census ACS → Block Group Demographics Table

    Joins acs_raw staging data with TIGER/Line block group geometry,
    computes derived demographic columns, splits DU sub-types using
    fixed ratios and a density-calibrated sigmoid for single-family lots.

    Inputs (via dbt vars):
        source_schema: Schema containing source tables (default public)
        acs_raw_table: acs_raw table name (default acs_raw)
        tiger_bg_table: tiger_block_groups table name (default tiger_block_groups)
        year: ACS data year
        state_fips: Two-digit state FIPS code
        county_fips: Three-digit county FIPS code
        detsf_sl_ratio: Fallback small-lot ratio when geometry unavailable (default 0.40)
        sl_density_threshold: Density threshold for small-lot sigmoid (default 8.0)
        mf_2_9_to_mf2to4_ratio: Fraction of 2-9 unit buildings classified as 2-4 (default 0.40)

    Output: census.acs_block_group — persistent table read by _allocate_demographics
#}

{{ config(materialized='table', schema='census',
    indexes=[
        {'columns': ['geometry'], 'type': 'gist'},
        {'columns': ['geoid'], 'unique': True},
    ])
}}

{% set year = var('year', 2022) %}
{% set state_fips = var('state_fips') %}
{% set county_fips = var('county_fips') %}
{% set detsf_sl_ratio = var('detsf_sl_ratio', 0.40) %}
{% set sl_density_threshold = var('sl_density_threshold', 8.0) %}
{% set mf_2_9_to_mf2to4_ratio = var('mf_2_9_to_mf2to4_ratio', 0.40) %}
{% set k_steepness = var('k_steepness', 0.5) %}
{% set tiger_bg_vintage = var('tiger_bg_vintage', '2013') %}

WITH raw_derived AS (
    SELECT
        a.state || a.county || a.tract || a."block_group" AS geoid,
        ST_Multi(ST_GeomFromText(tbg.geometry, 4326)) AS geometry,
        COALESCE(a.b01001_001_e, 0)::numeric AS pop,
        COALESCE(a.b25003_001_e, 0)::numeric AS hh,
        COALESCE(a.b25024_001_e, 0)::numeric AS du,
        -- DU types
        COALESCE(a.b25024_002_e, 0)::numeric AS du_detsf,
        COALESCE(a.b25024_003_e, 0)::numeric AS du_attsf,
        (COALESCE(a.b25024_004_e, 0) + COALESCE(a.b25024_005_e, 0)
            + COALESCE(a.b25024_006_e, 0))::numeric AS du_mf_2_9,
        (COALESCE(a.b25024_007_e, 0) + COALESCE(a.b25024_008_e, 0)
            + COALESCE(a.b25024_009_e, 0))::numeric AS du_mf_10p,
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
    FROM {{ source('brewgis', 'acs_raw') }} a
    JOIN {{ source('brewgis', 'tiger_block_groups') }} tbg
        ON tbg.geoid = a.state || a.county || a.tract || a."block_group"
        AND tbg.vintage = '{{ tiger_bg_vintage }}'
    WHERE a.year = {{ year }}
      AND a.state = '{{ state_fips }}'
      AND a.county = '{{ county_fips }}'
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
        -- DU sub-type splits (fixed ratios)
        ROUND(du_mf_2_9 * {{ mf_2_9_to_mf2to4_ratio }}, 1) AS du_mf2to4,
        ROUND(du_mf_2_9 * (1 - {{ mf_2_9_to_mf2to4_ratio }}) + du_mf_10p, 1) AS du_mf5p,
        -- Density-calibrated single-family lot split
        CASE
            WHEN du_detsf > 0 AND geometry IS NOT NULL AND ST_IsValid(geometry)
            THEN LEAST(1.0, GREATEST(0.0,
                1.0 / (1.0 + EXP(-{{ k_steepness }} * (
                    (du_detsf / NULLIF(ST_Area(ST_Transform(geometry, 6933)) / 4046.86, 0))
                    - {{ sl_density_threshold }}
                )))
            ))
            ELSE {{ detsf_sl_ratio }}
        END AS sl_ratio
    FROM raw_derived
)
SELECT
    geoid,
    geometry,
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
FROM derived_with_pcts

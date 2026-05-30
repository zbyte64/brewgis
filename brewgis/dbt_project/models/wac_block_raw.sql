{#
    LEHD LODES WAC → Block-Level Employment (Raw CNS Split)


    Joins lodes_raw staging data with TIGER/Line block geometry (15-digit
    GEOID), splits CNS employment into NAICS-based sub-sectors using CBP
    proportions, and distributes CNS16 (unclassified) employment
    proportionally across sub-sectors.

    Geometry resolution — three-tier fallback:
      Tier 1: exact 15-digit geoid match to tiger_blocks (preferred)
      Tier 2: 12-digit block group match to tiger_block_groups
      Tier 3: any block group in the same census tract (tiger_block_groups)
      Excluded: blocks with no TIGER match at any tier

    Inputs (via dbt vars):
        source_schema: Schema containing source tables (default public)
        lodes_raw_table: lodes_raw table name (default lodes_raw)
        tiger_block_table: tiger_blocks table name (default tiger_blocks)
        tiger_bg_table: tiger_block_groups table name (default tiger_block_groups,
            still used for geometric fallback)
        year: LEHD data year
        state_fips, county_fips: County identifier
        cbp_11..cbp_721: CBP NAICS proportion parameters

    Output: lehd.wac_block_raw — intermediate table consumed by wac_block
#}

{{ config(materialized='table', schema='lehd',
    indexes=[{'columns': ['geometry'], 'type': 'gist'}])
}}

{% set year = var('year', 2021) %}
{% set cbp_11 = var('cbp_11', 0.0) %}
{% set cbp_21 = var('cbp_21', 0.0) %}
{% set cbp_48 = var('cbp_48', 0.0) %}
{% set cbp_49 = var('cbp_49', 0.0) %}
{% set cbp_22 = var('cbp_22', 0.0) %}
{% set cbp_42 = var('cbp_42', 0.0) %}
{% set cbp_721 = var('cbp_721', 0.0) %}
{% set state_fips = var('state_fips', '06') %}
{% set county_fips = var('county_fips', '067') %}
{% set tiger_block_vintage = var('tiger_block_vintage', '2020') %}
{% set tiger_bg_vintage = var('tiger_bg_vintage', '2023') %}

-- Sub-sector metadata: maps each employment sub-sector to its aggregate column.
-- The `agg` field is used to compute aggregate totals for scaling.
{% set sub_sectors = [
    {'col': 'emp_agriculture',           'agg': 'emp_ind'},
    {'col': 'emp_extraction',            'agg': 'emp_ind'},
    {'col': 'emp_construction',          'agg': 'emp_ind'},
    {'col': 'emp_manufacturing',         'agg': 'emp_ind'},
    {'col': 'emp_transport_warehousing', 'agg': 'emp_ind'},
    {'col': 'emp_utilities',             'agg': 'emp_ind'},
    {'col': 'emp_wholesale',             'agg': 'emp_ind'},
    {'col': 'emp_retail_services',       'agg': 'emp_ret'},
    {'col': 'emp_office_services',       'agg': 'emp_off'},
    {'col': 'emp_education',             'agg': 'emp_pub'},
    {'col': 'emp_medical_services',      'agg': 'emp_off'},
    {'col': 'emp_arts_entertainment',    'agg': 'emp_ret'},
    {'col': 'emp_accommodation',         'agg': 'emp_ret'},
    {'col': 'emp_restaurant',            'agg': 'emp_ret'},
    {'col': 'emp_other_services',        'agg': 'emp_ret'},
    {'col': 'emp_public_admin',          'agg': 'emp_pub'},
    {'col': 'emp_military',              'agg': none},
] %}

-- Note: sacog_var metadata removed — SACOG calibration is deprecated.
-- Sub-sectors use CBP proportions exclusively.
{% set aggregates = {
    'emp_ret': ['emp_retail_services', 'emp_restaurant', 'emp_accommodation', 'emp_arts_entertainment', 'emp_other_services'],
    'emp_off': ['emp_office_services', 'emp_medical_services'],
    'emp_pub': ['emp_education', 'emp_public_admin'],
    'emp_ind': ['emp_manufacturing', 'emp_wholesale', 'emp_transport_warehousing', 'emp_utilities', 'emp_construction', 'emp_extraction', 'emp_agriculture'],
} %}

-- Pre-compute best-available TIGER geometry for each LODES block.
-- Tier 1: exact 15-digit geoid match on tiger_blocks.
-- Tier 2: 12-digit block group match on tiger_block_groups.
-- Tier 3: fallback to any block group in the same census tract.
-- Blocks with no TIGER match at any tier get NULL geometry and are
-- excluded from the final result (cannot spatially allocate without geometry).
WITH lodes_blocks AS (
    SELECT DISTINCT
        w_geocode AS block_geoid,
        LEFT(w_geocode, 12) AS bg,
        LEFT(w_geocode, 11) AS tract
    FROM {{ source('brewgis', 'lodes_raw') }}
    WHERE year = {{ year }}
      AND LEFT(w_geocode, 5) = '{{ state_fips }}' || '{{ county_fips }}'
),

block_geometry_map AS (
    SELECT
        lb.block_geoid,
        COALESCE(
            tb.geometry,
            tbg.geometry,
            tbg_fallback.geometry
        ) AS geometry
    FROM lodes_blocks lb
    -- Tier 1: exact 15-digit block match
    LEFT JOIN {{ source('brewgis', 'tiger_blocks') }} tb
        ON lb.block_geoid = tb.geoid
        AND tb.vintage = '{{ tiger_block_vintage }}'
    -- Tier 2: 12-digit block group match
    LEFT JOIN {{ source('brewgis', 'tiger_block_groups') }} tbg
        ON lb.bg = tbg.geoid
        AND tbg.vintage = '{{ tiger_bg_vintage }}'
    -- Tier 3: any block group in the same census tract
    LEFT JOIN LATERAL (
        SELECT geometry FROM {{ source('brewgis', 'tiger_block_groups') }}
        WHERE geoid LIKE lb.tract || '%'
          AND vintage = '{{ tiger_bg_vintage }}'
        LIMIT 1
    ) tbg_fallback ON tb.geoid IS NULL AND tbg.geoid IS NULL
    WHERE COALESCE(tb.geometry, tbg.geometry, tbg_fallback.geometry) IS NOT NULL
),

cbp_sub_sectors AS (
    SELECT
        lr.w_geocode AS geoid,
        ST_Multi(bm.geometry) AS geometry,
        lr.c000,
        -- CNS01 -> goods producing: agriculture (11), extraction (21), remainder construction (23)
        CASE WHEN COALESCE(lr.cns01, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns01, 0)::numeric * {{ cbp_11 }}, 1))
            ELSE 0 END AS emp_agriculture_cbp,
        CASE WHEN COALESCE(lr.cns01, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns01, 0)::numeric * {{ cbp_21 }}, 1))
            ELSE 0 END AS emp_extraction_cbp,
        CASE WHEN COALESCE(lr.cns01, 0) > 0
            THEN GREATEST(0, COALESCE(lr.cns01, 0)::numeric
                - ROUND(COALESCE(lr.cns01, 0)::numeric * {{ cbp_11 }}, 1)
                - ROUND(COALESCE(lr.cns01, 0)::numeric * {{ cbp_21 }}, 1))
            ELSE 0 END AS emp_construction_cbp,
        -- CNS02 -> manufacturing
        COALESCE(lr.cns02, 0)::numeric AS emp_manufacturing_cbp,
        -- CNS03 -> trade/transport/utilities
        CASE WHEN COALESCE(lr.cns03, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns03, 0)::numeric * ({{ cbp_48 }} + {{ cbp_49 }}), 1))
            ELSE 0 END AS emp_transport_warehousing_cbp,
        CASE WHEN COALESCE(lr.cns03, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns03, 0)::numeric * {{ cbp_22 }}, 1))
            ELSE 0 END AS emp_utilities_cbp,
        CASE WHEN COALESCE(lr.cns03, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns03, 0)::numeric * {{ cbp_42 }}, 1))
            ELSE 0 END AS emp_wholesale_cbp,
        CASE WHEN COALESCE(lr.cns03, 0) > 0
            THEN GREATEST(0, COALESCE(lr.cns03, 0)::numeric
                - ROUND(COALESCE(lr.cns03, 0)::numeric * ({{ cbp_48 }} + {{ cbp_49 }}), 1)
                - ROUND(COALESCE(lr.cns03, 0)::numeric * {{ cbp_22 }}, 1)
                - ROUND(COALESCE(lr.cns03, 0)::numeric * {{ cbp_42 }}, 1))
            ELSE 0 END AS emp_retail_services_cbp,
        -- CNS04-CNS09 -> office services
        (COALESCE(lr.cns04, 0) + COALESCE(lr.cns05, 0) + COALESCE(lr.cns06, 0)
            + COALESCE(lr.cns07, 0) + COALESCE(lr.cns08, 0) + COALESCE(lr.cns09, 0)
        )::numeric AS emp_office_services_cbp,
        -- CNS10 -> education
        COALESCE(lr.cns10, 0)::numeric AS emp_education_cbp,
        -- CNS11 -> medical
        COALESCE(lr.cns11, 0)::numeric AS emp_medical_services_cbp,
        -- CNS12 -> arts/entertainment
        COALESCE(lr.cns12, 0)::numeric AS emp_arts_entertainment_cbp,
        -- CNS13 -> accommodation/food: accommodation (721), remainder restaurant (722)
        CASE WHEN COALESCE(lr.cns13, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns13, 0)::numeric * {{ cbp_721 }}, 1))
            ELSE 0 END AS emp_accommodation_cbp,
        CASE WHEN COALESCE(lr.cns13, 0) > 0
            THEN GREATEST(0, COALESCE(lr.cns13, 0)::numeric
                - ROUND(COALESCE(lr.cns13, 0)::numeric * {{ cbp_721 }}, 1))
            ELSE 0 END AS emp_restaurant_cbp,
        -- CNS14 -> other services
        COALESCE(lr.cns14, 0)::numeric AS emp_other_services_cbp,
        -- CNS15 + CNS18-20 -> public admin (all government sectors)
        COALESCE(lr.cns15, 0)::numeric AS emp_public_admin_cbp,
        -- CNS18-20: government workers (Federal, State, Local) distributed
        -- to education/medical/public_admin via cns18_20_*_frac vars.
        COALESCE(lr.cns18, 0) + COALESCE(lr.cns19, 0) + COALESCE(lr.cns20, 0) AS cns18_20_govt,
        -- CNS17 -> military
        COALESCE(lr.cns17::numeric, 0)::numeric AS emp_military_cbp,
        -- CNS16 unclassified (distributed in later CTE)
        COALESCE(lr.cns16::numeric, 0)::numeric AS cns16_unclassified
    FROM {{ source('brewgis', 'lodes_raw') }} lr
    JOIN block_geometry_map bm
        ON lr.w_geocode = bm.block_geoid
    WHERE lr.year = {{ year }}
      AND LEFT(lr.w_geocode, 5) = '{{ state_fips }}' || '{{ county_fips }}'
),

-- Compute CBP-based aggregate columns and classified_total for CNS16 distribution.
-- These are computed once from CBP split values and reused throughout.
cbp_aggregates AS (
    SELECT
        *,
        -- CBP-based aggregate columns
        {% for agg, cols in aggregates.items() %}
        ({% for c in cols %}{{ c }}_cbp{% if not loop.last %} + {% endif %}{% endfor %}) AS {{ agg }}_cbpm,
        {% endfor %}
        -- Total classified employment (excludes CNS16 and C000)
        (
            {% for s in sub_sectors %}
            {{ s.col }}_cbp{% if not loop.last %} + {% endif %}
            {% endfor %}
        ) AS classified_total
    FROM cbp_sub_sectors
),

-- Simplified: uses CBP proportions exclusively. SACOG calibration is removed.
calibrated_sectors AS (
    SELECT
        geoid,
        geometry,
        c000 AS emp,
        cns18_20_govt,
        cns16_unclassified,
        -- All sub-sectors use CBP proportions directly.
        {% for s in sub_sectors %}
        {{ s.col }}_cbp AS {{ s.col }}_calibrated,
        {% endfor %}
        emp_agriculture_cbp AS emp_ag,
        -- Aggregate columns
        {% for agg in aggregates.keys() %}
        {{ agg }}_cbp AS {{ agg }},
        {% endfor %}
        classified_total
    FROM cbp_aggregates
),

with_cns16 AS (
    SELECT
        geoid,
        geometry,
        emp,
        cns18_20_govt,
        -- Distribute CNS16: proportional when classified_total > 0,
        -- equal division when fully suppressed (classified_total = 0).
        {% for s in sub_sectors %}
        ROUND({{ s.col }}_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * {{ s.col }}_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS {{ s.col }},
        {% endfor %}
        emp_ag,
        {% for agg in aggregates.keys() %}
        {{ agg }}{% if not loop.last %},{% endif %}
        {% endfor %}
    FROM calibrated_sectors
),

-- Distribute CNS18-20 government employment across education, medical,
-- and public_admin sub-sectors using CBP-derived fractions.
-- The three fraction vars sum to 1.0 and are computed by _populate_wac_block
-- from CBP NAICS totals for 61 (education), 62 (medical), 92 (public admin).
with_govt AS (
    SELECT
        geoid,
        geometry,
        emp,
        {% for s in sub_sectors %}
        {% set col = s.col %}
        {% if col == 'emp_education' %}
        ROUND(emp_education + cns18_20_govt * {{ var('cns18_20_edu_frac', 0) }}, 1) AS emp_education,
        {% elif col == 'emp_medical_services' %}
        ROUND(emp_medical_services + cns18_20_govt * {{ var('cns18_20_med_frac', 0) }}, 1) AS emp_medical_services,
        {% elif col == 'emp_public_admin' %}
        ROUND(emp_public_admin + cns18_20_govt * {{ var('cns18_20_pub_frac', 1) }}, 1) AS emp_public_admin,
        {% else %}
        {{ col }},
        {% endif %}
        {% endfor %}
        emp_ag,
        {% for agg in aggregates.keys() %}
        {{ agg }}{% if not loop.last %},{% endif %}
        {% endfor %}
    FROM with_cns16
)

SELECT * FROM with_govt

{#
    LEHD LODES WAC → Block Group Employment (Raw CNS Split)

    Joins lodes_raw staging data with TIGER/Line block group geometry,
    splits CNS employment into NAICS-based sub-sectors using CBP proportions,
    applies SACOG calibration via explicit ratio vars, and distributes
    CNS16 (unclassified) employment proportionally across sub-sectors.

    For blocks whose block group does not exist in TIGER, falls back to
    any block group in the same census tract. Blocks whose tract also has
    no TIGER match are excluded (their employment cannot be spatially
    allocated without geometry).

    SACOG calibration uses 17 explicit ratio vars (sacog_*_ratio). When these
    vars are provided, sub-sectors are computed as aggregate * ratio instead
    of CBP proportions. When absent (non-SACOG counties), CBP proportions
    are used. This replaces the old is_sacog boolean + hardcoded fractions.

    CNS16 distribution uses CBP-based classified_total as the denominator
    and calibrated sub-sector values as the numerators — matching the
    existing model's behavior.

    Inputs (via dbt vars):
        source_schema: Schema containing source tables (default public)
        lodes_raw_table: lodes_raw table name (default lodes_raw)
        tiger_bg_table: tiger_block_groups table name (default tiger_block_groups)
        year: LEHD data year
        state_fips, county_fips: County identifier
        cbp_11..cbp_721: CBP NAICS proportion parameters
        sacog_*_ratio: 17 optional ratio vars (default none — use CBP proportions)

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
{% set tiger_bg_vintage = var('tiger_bg_vintage', '2023') %}

-- Sub-sector metadata for loop-driven SACOG calibration, CNS16 distribution,
-- and aggregate column computation. Each sub-sector's agg field indicates
-- the aggregate column used for SACOG calibration (null for military).
-- sacog_zero indicates sub-sectors SACOG always zeros.
{% set sub_sectors = [
    {'col': 'emp_agriculture',           'agg': 'emp_ind',  'sacog_var': 'sacog_agriculture_ratio'},
    {'col': 'emp_extraction',            'agg': 'emp_ind',  'sacog_var': 'sacog_extraction_ratio'},
    {'col': 'emp_construction',          'agg': 'emp_ind',  'sacog_var': 'sacog_construction_ratio'},
    {'col': 'emp_manufacturing',         'agg': 'emp_ind',  'sacog_var': 'sacog_manufacturing_ratio'},
    {'col': 'emp_transport_warehousing', 'agg': 'emp_ind',  'sacog_var': 'sacog_transport_warehousing_ratio'},
    {'col': 'emp_utilities',             'agg': 'emp_ind',  'sacog_var': 'sacog_utilities_ratio'},
    {'col': 'emp_wholesale',             'agg': 'emp_ind',  'sacog_var': 'sacog_wholesale_ratio'},
    {'col': 'emp_retail_services',       'agg': 'emp_ret',  'sacog_var': 'sacog_retail_services_ratio'},
    {'col': 'emp_office_services',       'agg': 'emp_off',  'sacog_var': 'sacog_office_services_ratio'},
    {'col': 'emp_education',             'agg': 'emp_pub',  'sacog_var': 'sacog_education_ratio'},
    {'col': 'emp_medical_services',      'agg': 'emp_off',  'sacog_var': 'sacog_medical_services_ratio'},
    {'col': 'emp_arts_entertainment',    'agg': 'emp_ret',  'sacog_var': 'sacog_arts_entertainment_ratio'},
    {'col': 'emp_accommodation',         'agg': 'emp_ret',  'sacog_var': 'sacog_accommodation_ratio'},
    {'col': 'emp_restaurant',            'agg': 'emp_ret',  'sacog_var': 'sacog_restaurant_ratio'},
    {'col': 'emp_other_services',        'agg': 'emp_ret',  'sacog_var': 'sacog_other_services_ratio'},
    {'col': 'emp_public_admin',          'agg': 'emp_pub',  'sacog_var': 'sacog_public_admin_ratio'},
    {'col': 'emp_military',              'agg': none,       'sacog_var': 'sacog_military_ratio'},
] %}

{% set aggregates = {
    'emp_ret': ['emp_retail_services', 'emp_restaurant', 'emp_accommodation', 'emp_arts_entertainment', 'emp_other_services'],
    'emp_off': ['emp_office_services', 'emp_medical_services'],
    'emp_pub': ['emp_education', 'emp_public_admin'],
    'emp_ind': ['emp_manufacturing', 'emp_wholesale', 'emp_transport_warehousing', 'emp_utilities', 'emp_construction', 'emp_extraction', 'emp_agriculture'],
} %}

-- Pre-compute best-available TIGER geometry for each LODES block group.
-- Tier 1: exact geoid match on block group.
-- Tier 2: fallback to any block group in the same census tract.
-- Blocks whose tract also has no TIGER match get NULL geometry and are
-- excluded from the final result (cannot spatially allocate without geometry).
WITH lodes_blocks AS (
    SELECT DISTINCT
        LEFT(w_geocode, 12) AS bg,
        LEFT(w_geocode, 11) AS tract
    FROM {{ source('brewgis', 'lodes_raw') }}
    WHERE year = {{ year }}
      AND LEFT(w_geocode, 5) = '{{ state_fips }}' || '{{ county_fips }}'
),

bg_geometry_map AS (
    SELECT
        lb.bg,
        COALESCE(
            tbg.geometry,
            tbg_fallback.geometry
        ) AS geometry
    FROM lodes_blocks lb
    LEFT JOIN {{ source('brewgis', 'tiger_block_groups') }} tbg
        ON lb.bg = tbg.geoid
        AND tbg.vintage = '{{ tiger_bg_vintage }}'
    LEFT JOIN LATERAL (
        SELECT geometry FROM {{ source('brewgis', 'tiger_block_groups') }}
        WHERE geoid LIKE lb.tract || '%'
          AND vintage = '{{ tiger_bg_vintage }}'
        LIMIT 1
    ) tbg_fallback ON tbg.geoid IS NULL
    WHERE COALESCE(tbg.geometry, tbg_fallback.geometry) IS NOT NULL
),

cbp_sub_sectors AS (
    SELECT
        LEFT(lr.w_geocode, 12) AS geoid,
        ST_Multi(ST_GeomFromText(bgm.geometry, 4326)) AS geometry,
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
        COALESCE(lr.cns15, 0)::numeric
            + COALESCE(lr.cns18::numeric, 0)::numeric
            + COALESCE(lr.cns19::numeric, 0)::numeric
            + COALESCE(lr.cns20::numeric, 0)::numeric AS emp_public_admin_cbp,
        -- CNS17 -> military
        COALESCE(lr.cns17::numeric, 0)::numeric AS emp_military_cbp,
        -- CNS16 unclassified (distributed in later CTE)
        COALESCE(lr.cns16::numeric, 0)::numeric AS cns16_unclassified
    FROM {{ source('brewgis', 'lodes_raw') }} lr
    JOIN bg_geometry_map bgm
        ON LEFT(lr.w_geocode, 12) = bgm.bg
    WHERE lr.year = {{ year }}
      AND LEFT(lr.w_geocode, 5) = '{{ state_fips }}' || '{{ county_fips }}'
),

-- Compute CBP-based aggregate columns and classified_total for CNS16 distribution.
-- These are computed once from CBP split values and reused throughout.
cbp_aggregates AS (
    SELECT
        *,
        -- CBP-based aggregate columns (used as multipliers for SACOG calibration)
        {% for agg, cols in aggregates.items() %}
        ({% for c in cols %}{{ c }}_cbp{% if not loop.last %} + {% endif %}{% endfor %}) AS {{ agg }}_cbp{% if not loop.last %},{% endif %}
        {% endfor %}
        , -- Total classified employment (excludes CNS16 and C000)
        (
            {% for s in sub_sectors %}
            {{ s.col }}_cbp{% if not loop.last %} + {% endif %}
            {% endfor %}
        ) AS classified_total
    FROM cbp_sub_sectors
),

calibrated_sectors AS (
    SELECT
        geoid,
        geometry,
        c000 AS emp,
        cns16_unclassified,
        -- Sub-sector: SACOG-calibrated or CBP-based.
        -- When a sacog_*_ratio var is provided, the sub-sector is computed as
        -- aggregate_cbp * ratio. When absent (non-SACOG county), the CBP split
        -- value is used directly.
        {% for s in sub_sectors %}
        {% set r = var(s.sacog_var, none) %}
        {% if s.agg is not none %}
            {% if r is not none %}
        CASE WHEN {{ s.agg }}_cbp > 0 THEN ROUND({{ s.agg }}_cbp * {{ r }}, 1) ELSE 0 END AS {{ s.col }}_calibrated{% if not loop.last %},{% endif %}
            {% else %}
        {{ s.col }}_cbp AS {{ s.col }}_calibrated{% if not loop.last %},{% endif %}
            {% endif %}
        {% else %}
            {# Military: not part of any aggregate, zeroed out when sacog_military_ratio is set #}
            {% if r is not none %}
        0 AS {{ s.col }}_calibrated{% if not loop.last %},{% endif %}
            {% else %}
        {{ s.col }}_cbp AS {{ s.col }}_calibrated{% if not loop.last %},{% endif %}
            {% endif %}
        {% endif %}
        {% endfor %}
        ,
        -- emp_ag: SACOG zeroes agriculture (and therefore emp_ag).
        -- Non-SACOG: emp_ag = emp_agriculture_cbp.
        {% set ag_var = var('sacog_agriculture_ratio', none) %}
        {% if ag_var is not none %}
        0 AS emp_ag,
        {% else %}
        emp_agriculture_cbp AS emp_ag,
        {% endif %}
        -- CBP-based aggregate columns (passed through for reference)
        {% for agg in aggregates.keys() %}
        {{ agg }}_cbp AS {{ agg }}{% if not loop.last %},{% endif %}
        {% endfor %}
        , classified_total
    FROM cbp_aggregates
),

with_cns16 AS (
    SELECT
        geoid,
        geometry,
        emp,
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
)

SELECT * FROM with_cns16

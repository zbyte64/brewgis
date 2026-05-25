{#
    LEHD LODES WAC → Block Group Employment (CBP County Scaling)

    Reads CNS-split sub-sector employment from wac_block_raw and applies
    two corrections:

    1. C000 gap distribution — LODES disclosure suppression means
       SUM(CNS01..CNS17) < C000 for many blocks.  This distributes the
       gap (C000 - SUM(sub-sectors)) proportionally across sub-sectors
       so that emp = SUM(sub-sectors) before CBP scaling begins.

    2. CBP county-level scaling — Census County Business Patterns (CBP)
       provides county-level employment totals that are not subject to
       disclosure suppression.  When CBP total > LODES total for a
       sub-sector, blocks are scaled up to match the CBP control total.
       The hybrid preserve fraction keeps a portion of the original LODES
       spatial distribution while distributing the remainder proportional
       to total employment.

    Aggregate columns (emp_ret, emp_off, emp_pub, emp_ind, emp_ag) and
    total emp are recomputed from scaled sub-sectors — ensuring internal
    consistency.

    Inputs (via dbt vars):
        cbp_county_*: CBP county-level absolute employment totals per sub-sector
        cbp_preserve_fraction: fraction of CBP total preserved via LODES scaling
            (default 0.5). Remainder is distributed proportionally.

    Output: lehd.wac_block — persistent table consumed by base_canvas_employment
#}

{{ config(materialized='table', schema='lehd',
    indexes=[{'columns': ['geometry'], 'type': 'gist'}])
}}

{% set cbp_preserve_fraction = var('cbp_preserve_fraction', 0.5) %}

-- Sub-sector metadata for loop-driven CBP scaling and aggregate recomputation.
-- cbp_var: dbt var holding the county-level CBP absolute total for this sub-sector.
-- agg: the aggregate column this sub-sector is part of (military excluded).
{% set sub_sectors = [
    {'col': 'emp_agriculture',           'agg': 'emp_ind',  'cbp_var': 'cbp_county_agriculture'},
    {'col': 'emp_extraction',            'agg': 'emp_ind',  'cbp_var': 'cbp_county_extraction'},
    {'col': 'emp_construction',          'agg': 'emp_ind',  'cbp_var': 'cbp_county_construction'},
    {'col': 'emp_manufacturing',         'agg': 'emp_ind',  'cbp_var': 'cbp_county_manufacturing'},
    {'col': 'emp_transport_warehousing', 'agg': 'emp_ind',  'cbp_var': 'cbp_county_transport_warehousing'},
    {'col': 'emp_utilities',             'agg': 'emp_ind',  'cbp_var': 'cbp_county_utilities'},
    {'col': 'emp_wholesale',             'agg': 'emp_ind',  'cbp_var': 'cbp_county_wholesale'},
    {'col': 'emp_retail_services',       'agg': 'emp_ret',  'cbp_var': 'cbp_county_retail_services'},
    {'col': 'emp_office_services',       'agg': 'emp_off',  'cbp_var': 'cbp_county_office_services'},
    {'col': 'emp_education',             'agg': 'emp_pub',  'cbp_var': 'cbp_county_education'},
    {'col': 'emp_medical_services',      'agg': 'emp_off',  'cbp_var': 'cbp_county_medical_services'},
    {'col': 'emp_arts_entertainment',    'agg': 'emp_ret',  'cbp_var': 'cbp_county_arts_entertainment'},
    {'col': 'emp_accommodation',         'agg': 'emp_ret',  'cbp_var': 'cbp_county_accommodation'},
    {'col': 'emp_restaurant',            'agg': 'emp_ret',  'cbp_var': 'cbp_county_restaurant'},
    {'col': 'emp_other_services',        'agg': 'emp_ret',  'cbp_var': 'cbp_county_other_services'},
    {'col': 'emp_public_admin',          'agg': 'emp_pub',  'cbp_var': 'cbp_county_public_admin'},
    {'col': 'emp_military',              'agg': none,       'cbp_var': none},
] %}

{% set aggregates = {
    'emp_ret': ['emp_retail_services', 'emp_restaurant', 'emp_accommodation', 'emp_arts_entertainment', 'emp_other_services'],
    'emp_off': ['emp_office_services', 'emp_medical_services'],
    'emp_pub': ['emp_education', 'emp_public_admin'],
    'emp_ind': ['emp_manufacturing', 'emp_wholesale', 'emp_transport_warehousing', 'emp_utilities', 'emp_construction', 'emp_extraction', 'emp_agriculture'],
    'emp_ag': ['emp_agriculture'],
} %}

-- Compute total_sub (sum of all sub-sectors pre-gap) and C000 gap.
-- The gap is C000 - SUM(sub-sectors), caused by LODES disclosure suppression
-- where a block has a C000 total but some CNS columns are suppressed to zero.
WITH raw_with_gap AS (
    SELECT
        *,
        (
            {% for s in sub_sectors %}
            COALESCE({{ s.col }}, 0){% if not loop.last %} + {% endif %}
            {% endfor %}
        ) AS total_sub,
        emp - (
            {% for s in sub_sectors %}
            COALESCE({{ s.col }}, 0){% if not loop.last %} + {% endif %}
            {% endfor %}
        ) AS c000_gap
    FROM {{ ref('wac_block_raw') }}
),
-- Apply C000 gap distribution: when c000_gap > 0, distribute the gap across
-- all 17 sub-sectors proportional to their current values. When total_sub = 0
-- (fully suppressed block), distribute equally.
gap_distributed AS (
    SELECT
        geoid,
        geometry,
        emp,
        emp_ag,
        emp_ret,
        emp_off,
        emp_pub,
        emp_ind,
        {% for s in sub_sectors %}
        COALESCE({{ s.col }}, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE({{ s.col }}, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS {{ s.col }}{% if not loop.last %},{% endif %}
        {% endfor %}
    FROM raw_with_gap
),
-- County-level LODES totals computed from gap_distributed (post-gap, pre-scaling).
-- These are the baseline against which CBP totals are compared.
county_lodes_totals AS (
    SELECT
        {% for s in sub_sectors %}
        COALESCE(SUM({{ s.col }}), 0) AS lodes_{{ s.col }},
        {% endfor %}
        COALESCE(SUM(emp), 0) AS total_proxy
    FROM gap_distributed
),

-- Apply CBP county-level scaling to each sub-sector.
-- Formula (per sub-sector, per the plan):
--   C = CBP county total, L = LODES county total (from gap_distributed rows),
--   v = block value, e = total proxy employment, T = total_proxy, p = preserve_fraction
--   - C <= L or C <= 0: v (no scaling)
--   - L > 0 and C > L: v * (C*p/L) + C*(1-p) * e/T
--   - L = 0 and C > 0 and T > 0: C * e/T
--   - T = 0: v (no data to scale against)
scaled AS (
    SELECT
        c.geoid,
        c.geometry,
        c.emp,
        {% for s in sub_sectors %}
        {% set C = var(s.cbp_var, 0.0) %}
        {% set has_cbp = s.cbp_var is not none %}
        {% if has_cbp %}
        CASE
            WHEN {{ C }} <= t.lodes_{{ s.col }} OR {{ C }} <= 0 THEN c.{{ s.col }}
            WHEN t.lodes_{{ s.col }} > 0 AND {{ C }} > t.lodes_{{ s.col }} THEN
                CASE WHEN c.{{ s.col }} > 0
                    THEN c.{{ s.col }} * ({{ C }} * {{ cbp_preserve_fraction }} / t.lodes_{{ s.col }})
                        + {{ C }} * (1.0 - {{ cbp_preserve_fraction }}) * c.emp / t.total_proxy
                    ELSE {{ C }} * (1.0 - {{ cbp_preserve_fraction }}) * c.emp / t.total_proxy
                END
            WHEN t.lodes_{{ s.col }} = 0 AND {{ C }} > 0 AND t.total_proxy > 0
            THEN {{ C }} * c.emp / t.total_proxy
            ELSE c.{{ s.col }}
        END AS {{ s.col }},
        {% else %}
        c.{{ s.col }} AS {{ s.col }},
        {% endif %}
        {% endfor %}
        c.emp_ag,
        c.emp_ret,
        c.emp_off,
        c.emp_pub,
        c.emp_ind,
        t.total_proxy
    FROM gap_distributed c
    CROSS JOIN county_lodes_totals t
)

-- Final output: recompute all aggregate columns from scaled sub-sectors
-- to ensure internal consistency. emp is the sum of all 17 sub-sectors.
SELECT
    geoid,
    geometry,
    -- Total employment: sum of all 17 scaled sub-sectors
    (
        {% for s in sub_sectors %}
        COALESCE({{ s.col }}, 0){% if not loop.last %} + {% endif %}
        {% endfor %}
    ) AS emp,
    -- Sub-sectors (scaled)
    {% for s in sub_sectors %}
    {{ s.col }},
    {% endfor %}
    -- Aggregate columns recomputed from scaled sub-sectors
    {% for agg, cols in aggregates.items() %}
    ({% for c in cols %}COALESCE({{ c }}, 0){% if not loop.last %} + {% endif %}{% endfor %}) AS {{ agg }}{% if not loop.last %},{% endif %}
    {% endfor %}
FROM scaled

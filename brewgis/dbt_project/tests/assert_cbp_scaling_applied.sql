{#
    Assert CBP county-level scaling brings aggregate group totals close to targets.

    Tests three critical aggregate groups:
      - emp_ind_total: manufacturing + wholesale + transport/warehousing + utilities + construction
      - emp_ret_total: retail_services + restaurant + accommodation + arts/entertainment + other_services
      - emp_off_total: office_services + medical_services

    When CBP vars are provided and non-zero for all three groups, each group's
    scaled total in wac_block must be within 5% of the CBP target.

    When all CBP vars are zero (no CBP data provided), the test verifies that
    wac_block totals match wac_block_raw totals within 1% — confirming that
    zero CBP vars are a no-op (no scaling applied) rather than zeroing out data.
#}

{% set cbp_ind_total = var('cbp_county_manufacturing', 0) + var('cbp_county_wholesale', 0)
    + var('cbp_county_transport_warehousing', 0) + var('cbp_county_utilities', 0)
    + var('cbp_county_construction', 0) %}
{% set cbp_ret_total = var('cbp_county_retail_services', 0) + var('cbp_county_restaurant', 0)
    + var('cbp_county_accommodation', 0) + var('cbp_county_arts_entertainment', 0)
    + var('cbp_county_other_services', 0) %}
{% set cbp_off_total = var('cbp_county_office_services', 0) + var('cbp_county_medical_services', 0) %}

WITH actual AS (
    SELECT
        COALESCE(SUM(emp_manufacturing + emp_wholesale + emp_transport_warehousing + emp_utilities + emp_construction), 0) AS actual_emp_ind_total,
        COALESCE(SUM(emp_retail_services + emp_restaurant + emp_accommodation + emp_arts_entertainment + emp_other_services), 0) AS actual_emp_ret_total,
        COALESCE(SUM(emp_office_services + emp_medical_services), 0) AS actual_emp_off_total
    FROM {{ ref('wac_block') }}
),

raw_total AS (
    SELECT
        COALESCE(SUM(emp_manufacturing + emp_wholesale + emp_transport_warehousing + emp_utilities + emp_construction), 0) AS raw_ind_total,
        COALESCE(SUM(emp_retail_services + emp_restaurant + emp_accommodation + emp_arts_entertainment + emp_other_services), 0) AS raw_ret_total,
        COALESCE(SUM(emp_office_services + emp_medical_services), 0) AS raw_off_total
    FROM {{ ref('wac_block_raw') }}
)

SELECT
    a.actual_emp_ind_total,
    a.actual_emp_ret_total,
    a.actual_emp_off_total,
    r.raw_ind_total,
    r.raw_ret_total,
    r.raw_off_total,
    {{ cbp_ind_total }} AS target_ind_total,
    {{ cbp_ret_total }} AS target_ret_total,
    {{ cbp_off_total }} AS target_off_total
FROM actual a, raw_total r
WHERE
    -- When CBP vars are all zero, verify totals match raw (no-op guard)
    (
        {{ cbp_ind_total }} = 0 AND {{ cbp_ret_total }} = 0 AND {{ cbp_off_total }} = 0
        AND (
            a.actual_emp_ind_total < r.raw_ind_total * 0.99
            OR a.actual_emp_ind_total > r.raw_ind_total * 1.01
            OR a.actual_emp_ret_total < r.raw_ret_total * 0.99
            OR a.actual_emp_ret_total > r.raw_ret_total * 1.01
            OR a.actual_emp_off_total < r.raw_off_total * 0.99
            OR a.actual_emp_off_total > r.raw_off_total * 1.01
        )
    )
    -- When CBP vars are provided, verify within 5% of targets
    OR (
        {{ cbp_ind_total }} > 0 AND (
            a.actual_emp_ind_total < {{ cbp_ind_total }} * 0.95
            OR a.actual_emp_ind_total > {{ cbp_ind_total }} * 1.05
        )
    )
    OR (
        {{ cbp_ret_total }} > 0 AND (
            a.actual_emp_ret_total < {{ cbp_ret_total }} * 0.95
            OR a.actual_emp_ret_total > {{ cbp_ret_total }} * 1.05
        )
    )
    OR (
        {{ cbp_off_total }} > 0 AND (
            a.actual_emp_off_total < {{ cbp_off_total }} * 0.95
            OR a.actual_emp_off_total > {{ cbp_off_total }} * 1.05
        )
    )

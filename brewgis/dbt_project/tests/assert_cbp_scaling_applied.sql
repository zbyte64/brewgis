{#
    Assert CBP county-level scaling brings sub-sector totals close to targets.

    When CBP vars are set higher than LODES county totals, the scaling formula
    should bring sub-sector totals to approximately match CBP targets. The
    pre/post-gap inconsistency in the formula (lodes_col from wac_block_raw,
    c.col from gap_distributed) causes the scaled value to overshoot or
    undershoot the CBP target.

    Fails because: the pre/post-gap mismatch causes the scaled total to deviate
    from the CBP target by more than 5%.
#}

WITH actual AS (
    SELECT
        COALESCE(SUM(emp_public_admin), 0) AS actual_emp_public_admin
    FROM {{ ref('wac_block') }}
)
SELECT
    actual_emp_public_admin,
    {{ var('cbp_county_public_admin', 0) }} AS target_emp_public_admin
FROM actual
WHERE {{ var('cbp_county_public_admin', 0) }} > 0
  AND (
    actual_emp_public_admin < {{ var('cbp_county_public_admin', 0) }} * 0.95
    OR actual_emp_public_admin > {{ var('cbp_county_public_admin', 0) }} * 1.05
  )

{#
    Assert CNS18-20 government employment from lodes_raw is mapped to emp_public_admin.

    CNS18 (Federal), CNS19 (State), and CNS20 (Local) represent government
    employment types that should be mapped to emp_public_admin alongside CNS15.
    Currently, they are not read by wac_block_raw (which only processes
    CNS01–CNS17), so CNS18-20 are silently dropped from sub-sector mapping.

    Uses wac_block_raw (before CBP scaling and gap distribution) so the
    test measures mapping completeness, not scaling correctness.
    Fails because: wac_block_raw.sql only has CNS split rules for CNS01–CNS17.
    CNS18-20 are not mapped to any sub-sector column.
#}

WITH expected AS (
    SELECT
        SUM(cns15 + cns18 + cns19 + cns20) AS expected_emp_pub
    FROM {{ source('brewgis', 'lodes_raw') }}
    WHERE year = {{ var('year', 2008) }}
      AND LEFT(w_geocode, 5) = '{{ var('state_fips', '06') }}' || '{{ var('county_fips', '067') }}'
),
actual AS (
    SELECT
        SUM(emp_public_admin) AS actual_emp_pub
    FROM {{ ref('wac_block_raw') }}
)
SELECT
    a.actual_emp_pub,
    e.expected_emp_pub,
    e.expected_emp_pub - a.actual_emp_pub AS shortfall
FROM actual a, expected e
WHERE a.actual_emp_pub < e.expected_emp_pub

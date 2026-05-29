{#
    Assert CNS18-20 employment is fully captured in sub-sector totals.

    CNS18-20 (Federal, State, Local government workers) are now distributed
    to emp_education, emp_medical_services, and emp_public_admin via the
    cns18_20_*_frac dbt vars.  This test verifies that the total sum of all
    CNS codes (cns01..cns20) from lodes_raw equals the sum of all sub-sector
    columns in wac_block_raw within a 1% tolerance — confirming CNS18-20
    is not silently dropped.

    Uses wac_block_raw (before CBP scaling and gap distribution) so the
    test measures mapping completeness, not scaling correctness.
#}

WITH lodes_sum AS (
    SELECT
        SUM(cns01 + cns02 + cns03 + cns04 + cns05 + cns06 + cns07
            + cns08 + cns09 + cns10 + cns11 + cns12 + cns13 + cns14
            + cns15 + cns16 + cns17 + cns18 + cns19 + cns20) AS lodes_all_cns
    FROM {{ source('brewgis', 'lodes_raw') }}
    WHERE year = {{ var('year', 2008) }}
      AND LEFT(w_geocode, 5) = '{{ var('state_fips', '06') }}' || '{{ var('county_fips', '067') }}'
),
actual AS (
    SELECT
        SUM(emp_agriculture + emp_extraction + emp_construction + emp_manufacturing
            + emp_transport_warehousing + emp_utilities + emp_wholesale
            + emp_retail_services + emp_office_services + emp_education
            + emp_medical_services + emp_arts_entertainment + emp_accommodation
            + emp_restaurant + emp_other_services + emp_public_admin + emp_military) AS actual_total
    FROM {{ ref('wac_block_raw') }}
)
SELECT
    a.actual_total,
    l.lodes_all_cns,
    ABS(a.actual_total - l.lodes_all_cns) AS abs_diff
FROM actual a, lodes_sum l
WHERE l.lodes_all_cns > 0
  AND ABS(a.actual_total - l.lodes_all_cns) / l.lodes_all_cns > 0.01

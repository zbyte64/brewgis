{#
    Assert that assessor building data is preferred over DU/emp estimation.

    Simulates the COALESCE logic from base_canvas_attributes building_areas CTE:

        COALESCE(
            bldg_area_*,
            CASE WHEN assessor_res_sqft IS NOT NULL AND du > 0
                THEN ROUND(assessor * (sub_type / total)::numeric, 1)
                ELSE NULL
            END,
            sub_type * default_sqft * factor
        )

    Covers eight cases:
      Case 1: assessor_res_sqft present, du > 0 → assessor distributed by DU share
      Case 2: assessor_res_sqft NULL            → DU-based estimation fallback
      Case 3: assessor_emp_sqft present, emp > 0 → assessor distributed by emp share
      Case 4: bldg_area_detsf_sl already set     → source value preserved
      Case 5: du = 0 with assessor data          → safety: division skip, fallback to 0
      Case 6: emp = 0 with assessor data         → safety: division skip, fallback to 0
      Case 7: assessor_res_sqft = 0              → assessor NOT used (0 * share = 0), same as estimation
      Case 8: assessor_emp_sqft present, emp>0, emp_subtype=0 → correctly 0
#}

{% set sqft_per_du = 1200.0 %}
{% set sqft_per_emp = 300.0 %}
{% set detsf_sl_factor = 0.8 %}

WITH test_cases AS (
    SELECT
        1 AS case_id,
        'assessor_res overrides DU estimation' AS description,
        NULL::double precision AS bldg_area_detsf_sl,
        10.0 AS du, 4.0 AS du_detsf_sl_v,
        15000.0 AS assessor_res_sqft,
        NULL::double precision AS assessor_emp_sqft,
        NULL::double precision AS emp,
        NULL::double precision AS emp_retail_services_v,
        6000.0 AS expected_sqft   -- 15000 * (4/10) = 6000

    UNION ALL
    SELECT
        2, 'NULL assessor falls back to DU estimation',
        NULL, 10.0, 4.0,
        NULL, NULL, NULL, NULL,
        3840.0   -- 4 * 1200 * 0.8 = 3840

    UNION ALL
    SELECT
        3, 'assessor_emp overrides EMP estimation',
        NULL, NULL, NULL,
        NULL, 25000.0, 50.0, 20.0,
        10000.0  -- 25000 * (20/50) = 10000

    UNION ALL
    SELECT
        4, 'pre-existing bldg_area takes priority over assessor',
        9999.0, 10.0, 4.0,
        15000.0, NULL, NULL, NULL,
        9999.0  -- source wins

    UNION ALL
    SELECT
        5, 'du=0 with assessor → assessor skipped, result = 0',
        NULL, 0.0, 0.0,
        15000.0, NULL, NULL, NULL,
        0.0  -- du_detsf_sl_v=0, 0 * 1200 * 0.8 = 0

    UNION ALL
    SELECT
        6, 'emp=0 with assessor → assessor skipped, emp_ret=0',
        NULL, NULL, NULL,
        NULL, 25000.0, 0.0, 0.0,
        0.0  -- emp=0 blocks CASE, emp_retail_services_v=0 → 0 * 300 = 0

    UNION ALL
    SELECT
        7, 'assessor_res_sqft=0 → correctly yields 0',
        NULL, 10.0, 4.0,
        0.0, NULL, NULL, NULL,
        0.0  -- 0 IS NOT NULL, 0 * (4/10) = 0 (assessor says zero sqft)

    UNION ALL
    SELECT
        8, 'assessor_emp with zero sub-type share',
        NULL, NULL, NULL,
        NULL, 25000.0, 50.0, 0.0,
        0.0  -- emp_retail_services_v=0 → 0 * 300 = 0
),

computed AS (
    SELECT
        case_id,
        description,
        expected_sqft,
        -- Residential building area COALESCE
        COALESCE(
            bldg_area_detsf_sl,
            CASE WHEN assessor_res_sqft IS NOT NULL AND du > 0
                THEN ROUND((assessor_res_sqft * du_detsf_sl_v / du)::numeric, 1)::double precision
                ELSE NULL
            END,
            du_detsf_sl_v * {{ sqft_per_du }} * {{ detsf_sl_factor }}
        ) AS computed_sqft_res,
        -- Employment building area COALESCE
        COALESCE(
            NULL::double precision,
            CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
                THEN ROUND((assessor_emp_sqft * emp_retail_services_v / emp)::numeric, 1)::double precision
                ELSE NULL
            END,
            emp_retail_services_v * {{ sqft_per_emp }}
        ) AS computed_sqft_emp
    FROM test_cases
)

-- Residential path failures
SELECT case_id, description, expected_sqft, ROUND(computed_sqft_res::numeric, 1) AS computed_sqft
FROM computed
WHERE ABS(computed_sqft_res - expected_sqft) > 0.01

UNION ALL

-- Employment path failures (case 3 only uses emp; cases 6,8 tested below)
SELECT case_id, description || ' (emp path)', expected_sqft, ROUND(computed_sqft_emp::numeric, 1)
FROM computed
WHERE case_id IN (3, 6, 8) AND ABS(computed_sqft_emp - expected_sqft) > 0.01

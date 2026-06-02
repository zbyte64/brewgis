AUDIT (
  name assert_assessor_building_area,
  dialect postgres
);
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
    6000.0 AS expected_sqft
  UNION ALL
  SELECT
    2, 'NULL assessor falls back to DU estimation',
    NULL, 10.0, 4.0,
    NULL, NULL, NULL, NULL,
    3840.0
  UNION ALL
  SELECT
    3, 'assessor_emp overrides EMP estimation',
    NULL, NULL, NULL,
    NULL, 25000.0, 50.0, 20.0,
    10000.0
  UNION ALL
  SELECT
    4, 'pre-existing bldg_area takes priority over assessor',
    9999.0, 10.0, 4.0,
    15000.0, NULL, NULL, NULL,
    9999.0
  UNION ALL
  SELECT
    5, 'du=0 with assessor -> assessor skipped, result = 0',
    NULL, 0.0, 0.0,
    15000.0, NULL, NULL, NULL,
    0.0
  UNION ALL
  SELECT
    6, 'emp=0 with assessor -> assessor skipped, emp_ret=0',
    NULL, NULL, NULL,
    NULL, 25000.0, 0.0, 0.0,
    0.0
  UNION ALL
  SELECT
    7, 'assessor_res_sqft=0 -> correctly yields 0',
    NULL, 10.0, 4.0,
    0.0, NULL, NULL, NULL,
    0.0
  UNION ALL
  SELECT
    8, 'assessor_emp with zero sub-type share',
    NULL, NULL, NULL,
    NULL, 25000.0, 50.0, 0.0,
    0.0
),
computed AS (
  SELECT
    case_id,
    description,
    expected_sqft,
    COALESCE(
      bldg_area_detsf_sl,
      CASE WHEN assessor_res_sqft IS NOT NULL AND du > 0
        THEN ROUND((assessor_res_sqft * du_detsf_sl_v / du)::numeric, 1)::double precision
        ELSE NULL
      END,
      du_detsf_sl_v * 1200.0 * 0.8
    ) AS computed_sqft_res,
    COALESCE(
      NULL::double precision,
      CASE WHEN assessor_emp_sqft IS NOT NULL AND emp > 0
        THEN ROUND((assessor_emp_sqft * emp_retail_services_v / emp)::numeric, 1)::double precision
        ELSE NULL
      END,
      emp_retail_services_v * 300.0
    ) AS computed_sqft_emp
  FROM test_cases
)
SELECT case_id, description, expected_sqft AS expected, ROUND(computed_sqft_res::numeric, 1) AS got
FROM computed
WHERE ABS(computed_sqft_res - expected_sqft) > 0.01
UNION ALL
SELECT case_id, description || ' (emp path)', expected_sqft, ROUND(computed_sqft_emp::numeric, 1)
FROM computed
WHERE case_id IN (3, 6, 8) AND ABS(computed_sqft_emp - expected_sqft) > 0.01

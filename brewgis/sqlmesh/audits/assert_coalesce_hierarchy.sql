AUDIT (
  name assert_coalesce_hierarchy,
  dialect postgres
);
WITH test_cases AS (
  SELECT
    1 AS case_id,
    'actual_living wins over footprint_imputed' AS description,
    2000.0::double precision AS actual_living_sqft,
    NULL::double precision AS actual_building_sqft,
    1500.0::double precision AS footprint_imputed_living_sqft,
    NULL::double precision AS footprint_imputed_building_sqft,
    1800.0::double precision AS estimated_living_sqft,
    NULL::double precision AS estimated_building_sqft,
    2000.0::double precision AS expected_res,
    NULL::double precision AS expected_emp
  UNION ALL
  SELECT
    2, 'footprint_imputed wins over estimated (living)',
    NULL, NULL,
    1500.0, NULL,
    1800.0, NULL,
    1500.0, NULL
  UNION ALL
  SELECT
    3, 'estimated fallback when actual and footprint are NULL',
    NULL, NULL,
    NULL, NULL,
    1800.0, NULL,
    1800.0, NULL
  UNION ALL
  SELECT
    4, 'all three NULL -> NULL for residential',
    NULL, NULL,
    NULL, NULL,
    NULL, NULL,
    NULL, NULL
  UNION ALL
  SELECT
    5, 'actual_building wins over footprint_imputed',
    NULL, 5000.0,
    NULL, 3500.0,
    NULL, 4000.0,
    NULL, 5000.0
  UNION ALL
  SELECT
    6, 'footprint_imputed wins over estimated (building)',
    NULL, NULL,
    NULL, 3500.0,
    NULL, 4000.0,
    NULL, 3500.0
  UNION ALL
  SELECT
    7, 'estimated fallback when actual and footprint are NULL (building)',
    NULL, NULL,
    NULL, NULL,
    NULL, 4000.0,
    NULL, 4000.0
  UNION ALL
  SELECT
    8, 'actual wins when both actual and footprint_imputed present',
    2000.0, NULL,
    1500.0, NULL,
    1800.0, NULL,
    2000.0, NULL
),
computed AS (
  SELECT
    case_id,
    description,
    expected_res,
    expected_emp,
    COALESCE(
      actual_living_sqft,
      footprint_imputed_living_sqft,
      estimated_living_sqft
    ) AS computed_res_sqft,
    COALESCE(
      actual_building_sqft,
      footprint_imputed_building_sqft,
      estimated_building_sqft
    ) AS computed_emp_sqft
  FROM test_cases
)
SELECT
  case_id,
  expected_res AS expected,
  ROUND(computed_res_sqft::numeric, 1) AS got
FROM computed
WHERE computed_res_sqft IS DISTINCT FROM expected_res
UNION ALL
SELECT
  case_id,
  expected_emp,
  ROUND(computed_emp_sqft::numeric, 1)
FROM computed
WHERE case_id IN (5, 6, 7)
  AND computed_emp_sqft IS DISTINCT FROM expected_emp

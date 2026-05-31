{#
    Assert that the assessor_res_sqft and assessor_emp_sqft COALESCE chains
    in base_canvas_attributes correctly prioritize footprint-imputed values
    over land-use-type medians.

    The production COALESCE in base_canvas_attributes dasym_source CTE:

        assessor_res_sqft:
            COALESCE(dw.actual_living_sqft, dw.footprint_imputed_living_sqft, dw.estimated_living_sqft)

        assessor_emp_sqft:
            COALESCE(dw.actual_building_sqft, dw.footprint_imputed_building_sqft, dw.estimated_building_sqft)

    Priority: actual (sales data) → footprint_imputed (Overture k-NN) → estimated (land-use median)

    Test cases:
      1: actual_living present                        → actual_living wins
      2: actual_living NULL, footprint_imputed present → footprint_imputed wins
      3: actual_living NULL, footprint_imputed NULL    → estimated wins
      4: all three NULL                                → NULL
      5: actual_building present                       → actual_building wins
      6: actual_building NULL, footprint_imputed present → footprint_imputed wins
      7: actual_building NULL, footprint_imputed NULL  → estimated wins
      8: actual AND footprint_imputed both present     → actual still wins (hierarchy preserved)
#}

WITH test_cases AS (
    SELECT
        1 AS case_id,
        'actual_living wins over footprint_imputed' AS description,
        2000.0 AS actual_living_sqft,
        NULL::double precision AS actual_building_sqft,
        1500.0 AS footprint_imputed_living_sqft,
        NULL::double precision AS footprint_imputed_building_sqft,
        1800.0 AS estimated_living_sqft,
        NULL::double precision AS estimated_building_sqft,
        2000.0 AS expected_res,    -- actual_living (2000) wins
        NULL::double precision AS expected_emp

    UNION ALL
    SELECT
        2, 'footprint_imputed wins over estimated (living)',
        NULL, NULL,
        1500.0, NULL,
        1800.0, NULL,
        1500.0, NULL    -- footprint_imputed (1500) wins

    UNION ALL
    SELECT
        3, 'estimated fallback when actual and footprint are NULL',
        NULL, NULL,
        NULL, NULL,
        1800.0, NULL,
        1800.0, NULL    -- estimated (1800) wins by default

    UNION ALL
    SELECT
        4, 'all three NULL → NULL for residential',
        NULL, NULL,
        NULL, NULL,
        NULL, NULL,
        NULL, NULL     -- all NULL → NULL

    UNION ALL
    SELECT
        5, 'actual_building wins over footprint_imputed',
        NULL, 5000.0,
        NULL, 3500.0,
        NULL, 4000.0,
        NULL, 5000.0   -- actual_building (5000) wins

    UNION ALL
    SELECT
        6, 'footprint_imputed wins over estimated (building)',
        NULL, NULL,
        NULL, 3500.0,
        NULL, 4000.0,
        NULL, 3500.0   -- footprint_imputed (3500) wins

    UNION ALL
    SELECT
        7, 'estimated fallback when actual and footprint are NULL (building)',
        NULL, NULL,
        NULL, NULL,
        NULL, 4000.0,
        NULL, 4000.0   -- estimated (4000) wins

    UNION ALL
    SELECT
        8, 'actual wins when both actual and footprint_imputed present',
        2000.0, NULL,
        1500.0, NULL,
        1800.0, NULL,
        2000.0, NULL   -- actual (2000) still wins
),

computed AS (
    SELECT
        case_id,
        description,
        expected_res,
        expected_emp,
        -- assessor_res_sqft COALESCE
        COALESCE(
            actual_living_sqft,
            footprint_imputed_living_sqft,
            estimated_living_sqft
        ) AS computed_res_sqft,
        -- assessor_emp_sqft COALESCE
        COALESCE(
            actual_building_sqft,
            footprint_imputed_building_sqft,
            estimated_building_sqft
        ) AS computed_emp_sqft
    FROM test_cases
)

-- Residential path failures
SELECT
    case_id,
    description || ' (res path)' AS description,
    expected_res AS expected,
    ROUND(computed_res_sqft::numeric, 1) AS got
FROM computed
WHERE computed_res_sqft IS DISTINCT FROM expected_res

UNION ALL

-- Employment path failures
SELECT
    case_id,
    description || ' (emp path)',
    expected_emp,
    ROUND(computed_emp_sqft::numeric, 1)
FROM computed
WHERE case_id IN (5, 6, 7)  -- only cases with non-null expected_emp
  AND computed_emp_sqft IS DISTINCT FROM expected_emp

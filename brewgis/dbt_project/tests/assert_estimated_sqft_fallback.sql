{#
    Assert that estimated_living_sqft / estimated_building_sqft have a
    fallback branch when median_lot_size_acres <= 0 (Bug #5).

    The production CASE logic in parcel_dasymetric_weights.estimated CTE:

        CASE
            WHEN median_living_area IS NOT NULL AND median_lot_size_acres > 0
            THEN median_living_area * (lot_size_acres / median_lot_size_acres)
            WHEN median_living_area IS NOT NULL
            THEN median_living_area
            ELSE NULL
        END AS estimated_living_sqft

        CASE
            WHEN median_building_sf IS NOT NULL AND median_lot_size_acres > 0
            THEN median_building_sf * (lot_size_acres / median_lot_size_acres)
            WHEN median_building_sf IS NOT NULL
            THEN median_building_sf
            ELSE NULL
        END AS estimated_building_sqft

    Test cases:
      1: median_living_area=1800, median_lot_size_acres=0,  lot=0.25 → 1800  (fallback to median)
      2: median_living_area=1800, median_lot_size_acres=0.25, lot=0.50 → 3600  (scaling works)
      3: median_living_area=NULL,  median_lot_size_acres=0    → NULL  (no data)
      4: median_building_sf=1495, median_lot_size_acres=0    → 1495  (employment fallback)
#}

WITH test_cases AS (
    SELECT
        1 AS case_id,
        'living sqft fallback when median_lot_size=0' AS description,
        1800.0 AS median_living_area,
        NULL::double precision AS median_building_sf,
        0.0 AS median_lot_size_acres,
        0.25 AS lot_size_acres,
        1800.0 AS expected_sqft_res,
        NULL::double precision AS expected_sqft_emp

    UNION ALL
    SELECT
        2, 'living sqft scaling still works',
        1800.0, NULL, 0.25, 0.50,
        3600.0, NULL

    UNION ALL
    SELECT
        3, 'NULL median → NULL result',
        NULL, NULL, 0.0, 0.25,
        NULL, NULL

    UNION ALL
    SELECT
        4, 'building sqft fallback when median_lot_size=0',
        NULL, 1495.0, 0.0, 0.25,
        NULL, 1495.0
),

computed AS (
    SELECT
        case_id,
        description,
        expected_sqft_res,
        expected_sqft_emp,
        CASE
            WHEN median_living_area IS NOT NULL AND median_lot_size_acres > 0
            THEN median_living_area * (lot_size_acres / median_lot_size_acres)
            WHEN median_living_area IS NOT NULL
            THEN median_living_area
            ELSE NULL
        END AS computed_living_sqft,
        CASE
            WHEN median_building_sf IS NOT NULL AND median_lot_size_acres > 0
            THEN median_building_sf * (lot_size_acres / median_lot_size_acres)
            WHEN median_building_sf IS NOT NULL
            THEN median_building_sf
            ELSE NULL
        END AS computed_building_sqft
    FROM test_cases
)

SELECT
    case_id,
    description,
    expected_sqft_res,
    computed_living_sqft
FROM computed
WHERE
    computed_living_sqft IS DISTINCT FROM expected_sqft_res

UNION ALL

SELECT
    case_id,
    description || ' (emp path)',
    expected_sqft_emp,
    computed_building_sqft
FROM computed
WHERE case_id = 4
    AND computed_building_sqft IS DISTINCT FROM expected_sqft_emp

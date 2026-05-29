{#
    Assert employment is conserved between wac_block source and allocated output.

    The sum of allocated employment in base_canvas_employment should approximately
    equal the sum of source employment in wac_block (within 5% tolerance).

    Uses ST_Intersection (accurate) by default.  Quick_parcel_clipping flag
    switches to ST_ClipByBox2D (faster but approximate bounding-box clip).
#}

WITH source AS (
    SELECT
        SUM(emp) AS source_emp
    FROM {{ ref('wac_block') }}
),
allocated AS (
    SELECT
        SUM(emp) AS allocated_emp
    FROM {{ ref('base_canvas_employment') }}
)
SELECT
    s.source_emp,
    a.allocated_emp,
    ABS(a.allocated_emp - s.source_emp) / GREATEST(s.source_emp, 1) AS pct_diff
FROM source s, allocated a
WHERE s.source_emp > 0
  AND ABS(a.allocated_emp - s.source_emp) / s.source_emp > 0.05

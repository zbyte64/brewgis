AUDIT (
  name assert_sacog_assessor_parcels_row_count,
  dialect postgres
);

-- Verify sacog_assessor_parcels model output matches the expected
-- count from the source table after sub-unit consolidation.
--
-- Expected = deduped normal parcels (lotsize>0, one per APN)
--           + consolidated sub-unit groups (prefix-8, valid geometry), computed
--             from the same raw source using the same logic the model uses.
--
-- This dynamic check automatically adjusts when dlt adds more parcels,
-- the consolidation ratio shifts, or NULL-geometry sub-units change count.
WITH normal_count AS (
    SELECT COUNT(*) AS cnt
    FROM (
        SELECT apn,
            ROW_NUMBER() OVER (
                PARTITION BY apn ORDER BY lotsize::double precision DESC NULLS LAST
            ) AS rn
        FROM public.sacog_assessor_parcels_raw
        WHERE lotsize IS NOT NULL AND lotsize::double precision > 0
    ) sub
    WHERE rn = 1
),
consolidated_count AS (
    SELECT COUNT(DISTINCT LEFT(apn, 8)) AS cnt
    FROM public.sacog_assessor_parcels_raw
    WHERE (lotsize IS NULL OR lotsize::double precision <= 0)
      AND geometry IS NOT NULL
),
expected AS (
    SELECT (SELECT cnt FROM normal_count) + (SELECT cnt FROM consolidated_count) AS cnt
),
actual AS (
    SELECT COUNT(*) AS cnt FROM @this_model
)
SELECT actual.cnt AS actual_rows
FROM actual, expected
WHERE actual.cnt != expected.cnt;

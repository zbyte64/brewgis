AUDIT (
  name assert_parcel_bft_classification_row_count,
  dialect postgres
);

-- Verify parcel_bft_resolved row count matches its upstream parcel table.
-- The model does a LEFT JOIN from the parcel table through each classification
-- tier, so every parcel gets exactly one output row.
WITH upstream AS (SELECT COUNT(*) AS cnt FROM @parcel_table),
actual AS (SELECT COUNT(*) AS cnt FROM @this_model)
SELECT actual.cnt AS actual_rows
FROM actual, upstream
WHERE actual.cnt != upstream.cnt;

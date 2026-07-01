AUDIT (
  name assert_bft_tier3_knn_non_empty,
  dialect postgres
);
-- Fail if tier3 KNN materializes zero rows, which would indicate all parcels
-- are classified by Tier0 or Tier1 (unusual but possible) or a data pipeline
-- failure upstream.
WITH actual AS (SELECT COUNT(*) AS cnt FROM @this_model)
SELECT cnt AS actual_rows
FROM actual
WHERE cnt = 0;

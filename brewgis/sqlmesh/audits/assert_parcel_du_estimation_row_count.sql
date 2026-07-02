AUDIT (
  name assert_parcel_du_estimation_row_count,
  dialect postgres
);

-- Verify parcel_du_estimation row count matches its upstream parcel table.
-- The model reads every row from parcel_dasymetric_weights via the parcel_input
-- CTE, so output count should equal that table.
WITH upstream AS (SELECT COUNT(*) AS cnt FROM @parcel_table),
actual AS (SELECT COUNT(*) AS cnt FROM @this_model)
SELECT actual.cnt AS actual_rows
FROM actual, upstream
WHERE actual.cnt != upstream.cnt;

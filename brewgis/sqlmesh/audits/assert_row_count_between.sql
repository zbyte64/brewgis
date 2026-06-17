AUDIT (
  name assert_row_count_between,
  dialect postgres
);

WITH actual AS (SELECT COUNT(*) AS cnt FROM @this_model)
SELECT cnt AS actual_rows
FROM actual
WHERE cnt < @min_rows OR cnt > @max_rows;

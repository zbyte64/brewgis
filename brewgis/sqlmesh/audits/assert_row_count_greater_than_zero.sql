AUDIT (
  name assert_row_count_greater_than_zero,
  dialect postgres
);

WITH actual AS (SELECT COUNT(*) AS cnt FROM @this_model)
SELECT cnt AS actual_rows
FROM actual
WHERE cnt <= 0;

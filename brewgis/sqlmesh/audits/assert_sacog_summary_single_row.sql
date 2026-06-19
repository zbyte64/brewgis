AUDIT (
  name assert_sacog_summary_single_row,
  dialect postgres
);
SELECT
  COUNT(*) AS row_count,
  'sacog_summary must have exactly 1 row, found ' || COUNT(*) AS failure_message
FROM @this_model
HAVING COUNT(*) != 1

AUDIT (
  name assert_column_non_negative,
  dialect postgres
);
-- Fails when the audited column holds a negative value in any row.
--
-- Attach to any model whose column is physically non-negative (trip counts,
-- miles, dollars) so that a unit or scale mistake surfaces at plan time
-- rather than silently poisoning every downstream SUM(). Modelled on
-- assert_row_count_between: the column is a parameter, so one audit covers
-- every such column.
--
-- SQLMesh treats the audit as failed when the query returns at least one
-- row, so the HAVING clause is what makes a clean table return zero rows --
-- the bare aggregate would otherwise always return one.
SELECT
  COUNT(*) AS negative_rows,
  MIN(@column_name) AS min_value
FROM @this_model
WHERE COALESCE(@column_name, 0) < 0
HAVING COUNT(*) > 0;

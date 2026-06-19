AUDIT (
  name assert_allocation_weights_non_negative,
  dialect postgres
);
SELECT
  source_id,
  target_id,
  weight
FROM @this_model
WHERE weight < 0 OR weight > 1.0001

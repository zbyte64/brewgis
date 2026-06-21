AUDIT (
  name assert_pop_dasym_weight_non_negative,
  dialect postgres
);
-- Population weight must be non-negative
SELECT
  apn,
  pop_dasym_weight
FROM @this_model
WHERE pop_dasym_weight < 0;

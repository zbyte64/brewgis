AUDIT (
  name assert_pop_dasym_weight_not_null,
  dialect postgres
);
-- Every parcel must have a population dasymetric weight
SELECT
  apn,
  pop_dasym_weight
FROM @this_model
WHERE pop_dasym_weight IS NULL;

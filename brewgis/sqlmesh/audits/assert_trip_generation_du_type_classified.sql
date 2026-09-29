AUDIT (
  name assert_trip_generation_du_type_classified,
  dialect postgres
);
-- Fails the plan when a parcel holds dwelling units whose built form declares
-- no housing class. The residential trip rate is chosen by that class, so an
-- unclassified built form silently generates zero residential trips — the
-- failure mode a blended per-form rate with a zero default produced (see
-- migration 0070). A built form that houses nobody is not an error: only
-- parcels whose built form gives them dwelling units are counted here.
SELECT
  es.parcel_id,
  es.built_form_key,
  es.du,
  es.du_type
FROM @this_model AS tg
JOIN @{scenario_schema}.core_end_state AS es
  ON es.parcel_id = tg.parcel_id
WHERE COALESCE(es.du, 0) > 0
  AND COALESCE(es.du_type, '') = '';

AUDIT (
  name assert_total_trips_conserved,
  dialect postgres
);
WITH trip_totals AS (
  SELECT
    SUM(trips_outbound) AS total_outbound,
    SUM(trips_inbound) AS total_inbound,
    SUM(trips_internal) AS total_internal
  FROM @this_model
),
trip_gen_totals AS (
  SELECT SUM(trips_total) AS total_trips_gen
  FROM @scenario_schema.trip_generation
)
SELECT
  tt.*,
  tg.total_trips_gen,
  ABS(tt.total_outbound - tt.total_inbound) AS outbound_inbound_diff,
  ABS(1.0 - (tt.total_outbound + tt.total_internal) / NULLIF(tg.total_trips_gen, 0)) AS conservation_ratio
FROM trip_totals tt
CROSS JOIN trip_gen_totals tg
WHERE
  ABS(tt.total_outbound - tt.total_inbound) / NULLIF(GREATEST(tt.total_outbound, tt.total_inbound), 0) > 0.01
  OR (tg.total_trips_gen > 0
    AND ABS(1.0 - (tt.total_outbound + tt.total_internal) / tg.total_trips_gen) > 0.01)
  OR (tg.total_trips_gen > 0
    AND ABS(1.0 - (tt.total_inbound + tt.total_internal) / tg.total_trips_gen) > 0.01)

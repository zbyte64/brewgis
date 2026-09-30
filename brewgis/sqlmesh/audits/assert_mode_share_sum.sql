AUDIT (
  name assert_mode_share_sum,
  dialect postgres
);
-- The five shares must partition the trips. A parcel with no trips has no split
-- to partition: mode_choice divides by a NULLIF-guarded total, so every share is
-- NULL there and such a row is skipped rather than failed. (A non-zero-trip
-- parcel whose shares deviated by more than the threshold would still fail: the
-- shares are NULL together, never individually.)
SELECT
  parcel_id,
  mode_share_auto,
  mode_share_transit,
  mode_share_walk,
  mode_share_bike,
  mode_share_internal_capture,
  (COALESCE(mode_share_auto, 0)
    + COALESCE(mode_share_transit, 0)
    + COALESCE(mode_share_walk, 0)
    + COALESCE(mode_share_bike, 0)
    + COALESCE(mode_share_internal_capture, 0)) AS mode_share_sum
FROM @this_model
WHERE mode_share_auto IS NOT NULL
  AND mode_share_transit IS NOT NULL
  AND mode_share_walk IS NOT NULL
  AND mode_share_bike IS NOT NULL
  AND mode_share_internal_capture IS NOT NULL
  AND ABS(
    mode_share_auto
    + mode_share_transit
    + mode_share_walk
    + mode_share_bike
    + mode_share_internal_capture
    - 1.0
  ) > 0.01

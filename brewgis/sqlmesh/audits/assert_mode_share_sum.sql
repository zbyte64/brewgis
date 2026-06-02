AUDIT (
  name assert_mode_share_sum,
  dialect postgres
);
SELECT
  parcel_id,
  mode_share_auto,
  mode_share_transit,
  mode_share_walk,
  mode_share_bike,
  (COALESCE(mode_share_auto, 0)
    + COALESCE(mode_share_transit, 0)
    + COALESCE(mode_share_walk, 0)
    + COALESCE(mode_share_bike, 0)) AS mode_share_sum
FROM @this
WHERE ABS(
  COALESCE(mode_share_auto, 0)
  + COALESCE(mode_share_transit, 0)
  + COALESCE(mode_share_walk, 0)
  + COALESCE(mode_share_bike, 0)
  - 1.0
) > 0.01

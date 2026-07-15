AUDIT (
  name assert_resnet_apn_coverage,
  dialect postgres
);

-- Assert that parcel_resnet_features contains features for at least
-- 1% of the assessor APNs in training_parcel_map.  Coverage below 1%
-- means NAIP download failed, chip extraction found zero chips, or
-- the APN join is broken.

WITH actual AS (
    SELECT COUNT(DISTINCT apn) AS cnt
    FROM @this_model
    WHERE apn IS NOT NULL
),
expected AS (
    SELECT COUNT(DISTINCT apn) AS cnt
    FROM brewgis.comparison.training_parcel_map
    WHERE apn IS NOT NULL
)
SELECT
    a.cnt AS actual_apns,
    e.cnt AS expected_apns,
    ROUND(100.0 * a.cnt / NULLIF(e.cnt, 0), 1) AS coverage_pct
FROM actual a, expected e
WHERE e.cnt > 0
  AND 100.0 * a.cnt / e.cnt < 1.0;

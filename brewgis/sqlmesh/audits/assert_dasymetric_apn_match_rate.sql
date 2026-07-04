AUDIT (
  name assert_dasymetric_apn_match_rate,
  dialect postgres
);
-- ≥95% of urban, developable APNs with du > 0 must have at least one
-- dasymetric intersection match. Unmatched APNs represent DU that cannot
-- be allocated to SACOG parcels, leading to systematic undercounts.
--
-- Uses a configurable threshold: pass FAIL_PCT=5 to allow up to 5% unmatched.
WITH
unmatched AS (
    SELECT COUNT(*) AS cnt
    FROM brewgis.assessor.parcel_du_estimation de
    WHERE de.du > 0
      AND de.land_development_category = 'urban'
      AND de.apn NOT IN (
          SELECT apn FROM @this_model
      )
),
total AS (
    SELECT COUNT(*) AS cnt
    FROM brewgis.assessor.parcel_du_estimation de
    WHERE de.du > 0
      AND de.land_development_category = 'urban'
)
SELECT
    u.cnt AS unmatched_apns,
    t.cnt AS total_urban_apns,
    ROUND((100.0 * u.cnt / NULLIF(t.cnt, 0))::numeric, 1) AS pct_unmatched
FROM unmatched u, total t
WHERE t.cnt > 0
  AND 100.0 * u.cnt / t.cnt > 5.0;

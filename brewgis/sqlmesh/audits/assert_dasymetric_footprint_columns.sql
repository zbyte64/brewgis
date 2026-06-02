AUDIT (
  name assert_dasymetric_footprint_columns,
  dialect postgres
);
SELECT
  apn,
  actual_living_sqft,
  footprint_imputed_living_sqft,
  'missing living sqft on parcel with building footprints' AS failure_reason
FROM @this AS m
WHERE EXISTS (
  SELECT 1
  FROM brewgis.assessor.parcel_building_footprints pbf
  WHERE pbf.apn = m.apn
    AND pbf.footprint_ratio > 0
)
AND m.actual_living_sqft IS NULL
AND m.footprint_imputed_living_sqft IS NULL

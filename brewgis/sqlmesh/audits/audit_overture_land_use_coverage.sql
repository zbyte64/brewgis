AUDIT (
  name audit_overture_land_use_coverage,
  dialect postgres
);
-- Assert that Overture land use classification is non-null for parcels
-- that overlap the Overture study area bounding box. Parcels outside
-- the study area will naturally have NULL results.
SELECT
  parcel_id,
  overture_land_use_subtype,
  overture_land_use_class,
  overture_category
FROM @this
WHERE overture_category IS NULL
  AND parcel_id IN (
    SELECT parcel_id
    FROM brewgis.base_canvas.base_canvas_geometry
    WHERE geometry && ST_MakeEnvelope(
      @VAR('overture_bbox_min_x', -121.87),
      @VAR('overture_bbox_min_y', 38.02),
      @VAR('overture_bbox_max_x', -121.01),
      @VAR('overture_bbox_max_y', 38.74),
      @VAR('default_srid', 4326)
    )
  );

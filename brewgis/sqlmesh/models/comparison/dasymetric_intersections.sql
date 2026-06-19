MODEL (
  name brewgis.comparison.dasymetric_intersections,
  kind FULL,
  audits (
    not_null(columns := (parcel_id, apn))
  )
);

-- SACOG Comparison Dasymetric Intersections — pre-computed spatial crosswalk.
--
-- Materializes the parcel_id ↔ apn mapping with pre-computed intersection area.
-- Uses LATERAL with LIMIT 1 instead of DISTINCT ON + full outer-join to
-- short-circuit the spatial join — for each SACOG parcel, only the best-matching
-- assessor parcel intersection area is computed.

SELECT sp.parcel_id, cand.apn, cand.intersect_area_sqft
FROM brewgis.comparison.sacog_parcel_shim sp
CROSS JOIN LATERAL (
    SELECT ap.apn,
        ST_Area(ST_Intersection(ST_Envelope(sp.geometry), ST_Envelope(ap.geometry))) AS intersect_area_sqft
    FROM brewgis.assessor.sacog_assessor_parcels ap
    WHERE ST_Intersects(sp.geometry, ap.geometry)
    ORDER BY intersect_area_sqft DESC NULLS LAST
    LIMIT 1
) cand
JOIN brewgis.assessor.parcel_dasymetric_weights dw ON cand.apn = dw.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_dasymetric_intersections_parcel_id
  ON brewgis.comparison.dasymetric_intersections (parcel_id);
ANALYZE brewgis.comparison.dasymetric_intersections;

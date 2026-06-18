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
-- This is the expensive spatial join step (ST_Intersects + ST_Intersection on
-- 500k SACOG parcels × 55k assessor parcels), separated so it runs once per
-- pipeline build instead of being inlined in sacog_comparison_dasymetric.
--
-- The DISTINCT ON picks the best matching assessor parcel for each SACOG parcel
-- by largest intersection envelope area, using ST_Envelope for performance.

SELECT DISTINCT ON (sp.parcel_id)
    sp.parcel_id,
    dw.apn,
    ST_Area(ST_Intersection(ST_Envelope(sp.geometry), ST_Envelope(dw.geometry))) AS intersect_area_sqft
FROM brewgis.comparison.sacog_parcel_shim sp
JOIN brewgis.assessor.parcel_dasymetric_weights dw
    ON ST_Intersects(sp.geometry, dw.geometry)
ORDER BY sp.parcel_id, intersect_area_sqft DESC NULLS LAST;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_dasymetric_intersections_parcel_id
  ON brewgis.comparison.dasymetric_intersections (parcel_id)
);
ANALYZE brewgis.comparison.dasymetric_intersections;

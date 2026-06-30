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
-- Uses CROSS JOIN LATERAL with GIST index-driven && bbox pre-filter and LIMIT 1
-- instead of a full spatial join + DISTINCT ON.  Each of the 125K sacog_parcel_shim
-- rows drives a single index lookup on sacog_assessor_parcels instead of building
-- a hash table over 508K rows.

WITH ranked AS (
    SELECT
        sp.parcel_id,
        ap.apn,
        ST_Area(ST_Intersection(ST_Envelope(sp.geometry), ST_Envelope(ap.geometry))) AS intersect_area_sqft
    FROM brewgis.comparison.sacog_parcel_shim sp
    CROSS JOIN LATERAL (
        SELECT ap.apn, ap.geometry
        FROM brewgis.assessor.sacog_assessor_parcels ap
        WHERE ap.geometry && sp.geometry
          AND ST_Intersects(sp.geometry, ap.geometry)
        ORDER BY ST_Area(ST_Intersection(ST_Envelope(sp.geometry), ST_Envelope(ap.geometry))) DESC
        LIMIT 1
    ) ap
)
SELECT r.parcel_id, r.apn, r.intersect_area_sqft
FROM ranked r
JOIN brewgis.assessor.parcel_dasymetric_weights dw ON r.apn = dw.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_dasymetric_intersections_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS idx_dasymetric_intersections_apn_@snapshot_hash
  ON @this_model USING btree (apn);
ANALYZE @this_model;

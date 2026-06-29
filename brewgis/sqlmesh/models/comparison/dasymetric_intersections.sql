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
-- Uses a DISTINCT ON pattern over a single spatial join instead of a
-- CROSS JOIN LATERAL with LIMIT 1.  This lets PostgreSQL plan one spatial
-- join (hash join or merge join with a single sort) instead of 502K
-- independent lateral subqueries, each with its own sort.

WITH candidates AS (
    SELECT sp.parcel_id, sp.geometry AS sp_geom,
           ap.apn, ap.geometry AS ap_geom
    FROM brewgis.comparison.sacog_parcel_shim sp
    JOIN brewgis.assessor.sacog_assessor_parcels ap
        ON ST_Intersects(sp.geometry, ap.geometry)
),
ranked AS (
    SELECT DISTINCT ON (parcel_id)
        parcel_id,
        apn,
        ST_Area(ST_Intersection(ST_Envelope(sp_geom), ST_Envelope(ap_geom))) AS intersect_area_sqft
    FROM candidates
    ORDER BY parcel_id,
        ST_Area(ST_Intersection(ST_Envelope(sp_geom), ST_Envelope(ap_geom))) DESC
)
SELECT r.parcel_id, r.apn, r.intersect_area_sqft
FROM ranked r
JOIN brewgis.assessor.parcel_dasymetric_weights dw ON r.apn = dw.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_dasymetric_intersections_parcel_id
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS idx_dasymetric_intersections_apn
  ON @this_model USING btree (apn);
ANALYZE @this_model;

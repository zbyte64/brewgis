MODEL (
  name brewgis.@{region}.dasymetric_intersections,
  kind FULL,
  description 'Parcel-to-APN crosswalk with the envelope intersection area used to allocate dasymetric quantities.',
  column_descriptions (
    parcel_id = 'Unique parcel identifier from the parcel shim.',
    apn = 'Assessor parcel number intersecting the parcel.',
    intersect_area_sqft = 'Area of the intersection between the parcel and APN EPSG:4326 envelopes (square degrees); used only as a relative weight per APN, so no unit conversion applies.'
  ),
  audits (
    not_null(columns := (parcel_id, apn))
  ),
  blueprints @region_blueprints()
);

-- Region Dasymetric Intersections — pre-computed parcel_id ↔ apn crosswalk.
--
-- Materializes the spatial join between the region's parcel shim and its
-- assessor parcels with pre-computed intersection area, using a GiST
-- index-driven && bbox pre-filter.
--
-- Both regions read a county assessor roll, so this is a true spatial
-- crosswalk in each: a parcel_shim parcel overlapping several assessor APNs
-- contributes one row per intersecting APN (correct proportional dasymetric
-- allocation), and a parcel whose geometry intersects no assessor parcel
-- contributes no row at all.

WITH intersections AS (
    SELECT
        sp.parcel_id,
        ap.apn,
        ST_Area(ST_Intersection(
            ST_Envelope(sp.geometry),
            ST_Envelope(ap.geometry)
        )) AS intersect_area_sqft
    FROM brewgis.@{region}.parcel_shim sp
    JOIN brewgis.@{region}.assessor_parcels ap
        ON ap.geometry && sp.geometry
        AND ST_Intersects(sp.geometry, ap.geometry)
)
SELECT i.parcel_id, i.apn, i.intersect_area_sqft
FROM intersections i
JOIN brewgis.@{region}.parcel_dasymetric_weights dw ON i.apn = dw.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_dasymetric_ix_parcel_')
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_dasymetric_ix_apn_')
  ON @this_model USING btree (apn);
  ANALYZE @this_model;

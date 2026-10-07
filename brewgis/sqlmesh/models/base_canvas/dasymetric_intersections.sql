MODEL (
  name brewgis.@{region}.dasymetric_intersections,
  kind FULL,
  description 'Parcel-to-APN crosswalk with the polygon overlap area used to allocate dasymetric quantities, one row per pair that shares area.',
  column_descriptions (
    parcel_id = 'Unique parcel identifier from the parcel shim.',
    apn = 'Assessor parcel number overlapping the parcel.',
    intersect_area_sqft = 'Area of the parcel and APN polygon overlap, measured in the region local_srid (sq ft); always > 0.'
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
--
-- The weight is the true polygon overlap, measured on the local_srid
-- geometries. Bounding-box overlap is not a proxy for it: a neighbour that only
-- shares an edge with the parcel has a large envelope overlap, so the old
-- envelope weights handed a share of every APN's dwelling units and jobs to the
-- parcels around it. Pairs that touch without sharing area are dropped.

WITH intersections AS (
    SELECT
        sp.parcel_id,
        ap.apn,
        @local_area_sqm(ST_Area(ST_Intersection(sp.local_geometry, ap.local_geometry)))
            * 10.7639 AS intersect_area_sqft
    FROM brewgis.@{region}.parcel_shim sp
    JOIN brewgis.@{region}.assessor_parcels ap
        ON ap.geometry && sp.geometry
        AND ST_Intersects(sp.geometry, ap.geometry)
)
SELECT i.parcel_id, i.apn, i.intersect_area_sqft
FROM intersections i
JOIN brewgis.@{region}.parcel_dasymetric_weights dw ON i.apn = dw.apn
WHERE i.intersect_area_sqft > 0;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_dasymetric_ix_parcel_')
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_dasymetric_ix_apn_')
  ON @this_model USING btree (apn);
  ANALYZE @this_model;

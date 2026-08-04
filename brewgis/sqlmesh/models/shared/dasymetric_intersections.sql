MODEL (
  name brewgis.@{region}.dasymetric_intersections,
  kind FULL,
  audits (
    not_null(columns := (parcel_id, apn))
  ),
  blueprints (
    (region := sacog),
    (region := fresno)
  )
);

-- Region Dasymetric Intersections — pre-computed parcel_id ↔ apn crosswalk.
--
-- Materializes the spatial join between the region's parcel shim and its
-- assessor parcels with pre-computed intersection area, using a GiST
-- index-driven && bbox pre-filter.
--
-- For regions with real assessor APNs (SACOG) every intersecting parcel-APN
-- pair contributes, enabling correct proportional dasymetric allocation.
-- For regions without assessor data (Fresno) the assessor_parcels adapter is
-- a pass-through of parcel_shim (apn = parcel_id, identical geometry), so the
-- self-join yields exactly one row per parcel with its full area — the same
-- column contract, no region-specific code here.

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
  CREATE INDEX IF NOT EXISTS idx_@{region}_dasymetric_ix_parcel_@snapshot_hash
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS idx_@{region}_dasymetric_ix_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  ANALYZE @this_model;

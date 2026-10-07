MODEL (
  name brewgis.sacog.training_parcel_map,
  kind FULL,
  description 'Reference parcel to assessor APN crosswalk for regressor training, one row per intersecting pair with the share of each parcel the overlap covers.',
  column_descriptions (
    parcel_id = 'Reference parcel identifier (parcel_id) from brewgis.sacog.parcel_shim.',
    apn = 'Assessor parcel number (APN) of the intersecting assessor parcel.',
    apn_overlap_share = 'Area of the reference/assessor polygon overlap divided by the assessor parcel area (0-1).',
    parcel_overlap_share = 'Area of the reference/assessor polygon overlap divided by the reference parcel area (0-1).'
  ),
  audits (
    not_null(columns := (parcel_id, apn, apn_overlap_share, parcel_overlap_share))
  )
);

-- Reference-Parcel-to-Assessor-APN crosswalk for regressor training data.
-- Same spatial join as dasymetric_intersections but deliberately excludes
-- the parcel_dasymetric_weights filter to avoid a DAG cycle:
--   dasymetric_intersections → parcel_dasymetric_weights → regressor → dasymetric_intersections
--
-- ST_Intersects also pairs parcels that only share an edge or a sliver, so
-- every pair carries the share of each side the true polygon overlap covers.
-- The trainers take an APN's label only from a reference parcel that covers
-- most of it and that it mostly covers (near one-to-one); without that an APN
-- inherits the dwelling units of whichever neighbour the join returns first.
-- Shares are area ratios within one CRS, so they need no unit conversion.

WITH intersections AS (
    SELECT
        sp.parcel_id,
        ap.apn,
        ST_Area(ST_Intersection(sp.geometry, ap.geometry)) AS overlap_area,
        ST_Area(ap.geometry) AS apn_area,
        ST_Area(sp.geometry) AS parcel_area
    FROM brewgis.sacog.parcel_shim sp
    JOIN brewgis.sacog.assessor_parcels ap
        ON ap.geometry && sp.geometry
        AND ST_Intersects(sp.geometry, ap.geometry)
)
SELECT DISTINCT ON (parcel_id, apn)
    parcel_id,
    apn,
    COALESCE(overlap_area / NULLIF(apn_area, 0), 0) AS apn_overlap_share,
    COALESCE(overlap_area / NULLIF(parcel_area, 0), 0) AS parcel_overlap_share
FROM intersections
ORDER BY parcel_id, apn, overlap_area DESC;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_training_parcel_map_parcel_id_')
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_training_parcel_map_apn_')
  ON @this_model USING btree (apn);
ANALYZE @this_model;

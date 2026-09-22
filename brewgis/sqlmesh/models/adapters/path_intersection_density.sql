MODEL (
  name brewgis.@{region}.path_intersection_density,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  description 'Per-parcel Overture path intersection density within 1/4 mile of the parcel centroid.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) the density belongs to.',
    path_intersection_density = 'Overture bike/path intersection points within 402 m of the centroid (per sq mi).',
    geometry = 'Parcel boundary geometry (EPSG:4326) from assessor_parcels.'
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  ),
  dialect postgres,
  blueprints @region_blueprints()
);

-- Region Overture Path Intersection Density — per-parcel pedestrian/bike
-- path intersection density (path intersection points within 1/4-mile of
-- the parcel centroid), consumed as a regressor feature.
--
-- Identical logic for every region: counts the region's path intersection
-- points around each assessor parcel centroid. Overture transport data is
-- global (bbox-filtered at the staging VIEW), so every region gets real
-- path density — no region-specific data source needed.

WITH density AS (
    SELECT
        sap.apn,
        COUNT(i.geometry)::double precision
            / (PI() * 402.0 * 402.0 / 2589988.11) AS path_intersection_density
    FROM brewgis.@{region}.assessor_parcels sap
    LEFT JOIN brewgis.@{region}.path_intersection_points i
        ON ST_DWithin(sap.centroid_local, i.geometry, 402.0)
    GROUP BY sap.apn
)
SELECT
    d.apn,
    COALESCE(d.path_intersection_density, 0.0) AS path_intersection_density,
    sap.geometry
FROM density d
JOIN brewgis.@{region}.assessor_parcels sap ON d.apn = sap.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_path_density_apn_')
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_path_density_geometry_')
  ON @this_model USING GIST (geometry);
  ANALYZE @this_model;

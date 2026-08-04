MODEL (
  name brewgis.@{region}.hwy_intersection_density,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  ),
  dialect postgres,
  blueprints (
    (region := sacog),
    (region := fresno)
  )
);

-- Region Overture Highway Intersection Density — per-parcel highway
-- interchange density (motorway/trunk intersection points within 1/4-mile
-- of the parcel centroid), consumed as a regressor feature.
--
-- Identical logic for every region: counts the region's highway intersection
-- points around each assessor parcel centroid. Overture transport data is
-- global (bbox-filtered at the staging VIEW), so every region gets real
-- highway density — no region-specific data source needed.

WITH density AS (
    SELECT
        sap.apn,
        COUNT(i.geometry)::double precision
            / (PI() * 402.0 * 402.0 / 2589988.11) AS highway_intersection_density
    FROM brewgis.@{region}.assessor_parcels sap
    LEFT JOIN brewgis.@{region}.hwy_intersection_points i
        ON ST_DWithin(sap.centroid_local, i.geometry, 402.0)
    GROUP BY sap.apn
)
SELECT
    d.apn,
    COALESCE(d.highway_intersection_density, 0.0) AS highway_intersection_density,
    sap.geometry
FROM density d
JOIN brewgis.@{region}.assessor_parcels sap ON d.apn = sap.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_@{region}_hwy_density_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS idx_@{region}_hwy_density_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  ANALYZE @this_model;

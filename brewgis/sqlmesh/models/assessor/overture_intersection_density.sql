MODEL (
  name brewgis.assessor.overture_intersection_density,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  ),
  dialect postgres
);

-- Overture Intersection Density — per-parcel intersection density from
-- Overture transport road segments.
--
-- All internal calc in local_srid (3310 meters). Final output geometry in 4326.

WITH driveable_segments AS (
    SELECT
        ST_Transform(
            ST_SetSRID(geometry, @VAR('default_srid', 4326)),
            @VAR('local_srid', 3310)
        ) AS local_geometry
    FROM brewgis.staging.overture_transport
    WHERE class IN ('motorway', 'primary', 'secondary', 'tertiary', 'residential', 'service')
      AND geometry IS NOT NULL
),

endpoints AS (
    SELECT ST_StartPoint(local_geometry) AS pt FROM driveable_segments
    UNION ALL
    SELECT ST_EndPoint(local_geometry) AS pt FROM driveable_segments
),

snapped_endpoints AS (
    SELECT ST_SnapToGrid(pt, 10) AS snapped_location
    FROM endpoints
),

street_nodes AS (
    SELECT snapped_location, COUNT(*) AS street_count
    FROM snapped_endpoints
    GROUP BY snapped_location
),

intersections AS (
    SELECT snapped_location AS geometry
    FROM street_nodes
    WHERE street_count >= 3
),

grid_bounds AS (
    SELECT
        ST_XMin(ext) AS xmin,
        ST_XMax(ext) AS xmax,
        ST_YMin(ext) AS ymin,
        ST_YMax(ext) AS ymax
    FROM (
        SELECT ST_Extent(local_geometry)::geometry AS ext
        FROM driveable_segments
    ) b
),

grid_cells AS (
    SELECT
        ST_MakeEnvelope(
            b.xmin + i * 865.0,
            b.ymin + j * 865.0,
            LEAST(b.xmin + (i + 1) * 865.0, b.xmax),
            LEAST(b.ymin + (j + 1) * 865.0, b.ymax),
            @VAR('local_srid', 3310)
        ) AS local_geometry,
        865.0 * 865.0 / 2589988.11 AS cell_area_sq_mi
    FROM grid_bounds b
    CROSS JOIN generate_series(
        0, GREATEST(1, CEIL((b.xmax - b.xmin) / 865.0)::int)
    ) AS i
    CROSS JOIN generate_series(
        0, GREATEST(1, CEIL((b.ymax - b.ymin) / 865.0)::int)
    ) AS j
),

grid_intersections AS (
    SELECT
        gc.local_geometry,
        gc.cell_area_sq_mi,
        COUNT(i.geometry)::double precision AS intersection_count
    FROM grid_cells gc
    LEFT JOIN intersections i
        ON ST_Intersects(gc.local_geometry, i.geometry)
    GROUP BY gc.local_geometry, gc.cell_area_sq_mi
),

intersection_density AS (
    SELECT
        local_geometry,
        intersection_count / NULLIF(cell_area_sq_mi, 0.0) AS density
    FROM grid_intersections
),

parcels_local AS (
    SELECT
        apn,
        geometry,
        ST_Transform(geometry, @VAR('local_srid', 3310)) AS local_geometry
    FROM brewgis.assessor.sacog_assessor_parcels
)

SELECT
    pl.apn,
    COALESCE(AVG(id.density), 0.0)::double precision AS intersection_density,
    pl.geometry
FROM parcels_local pl
LEFT JOIN intersection_density id
    ON ST_Intersects(pl.local_geometry, id.local_geometry)
GROUP BY pl.apn, pl.geometry;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_overture_intersection_density_apn
  ON brewgis.assessor.overture_intersection_density (apn)
);
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_overture_intersection_density_geometry
  ON brewgis.assessor.overture_intersection_density USING GIST (geometry)
);
ANALYZE brewgis.assessor.overture_intersection_density;

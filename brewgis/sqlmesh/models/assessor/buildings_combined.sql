MODEL (
  name brewgis.staging.buildings_combined,
  kind FULL,
  gateway: duckdb
);

/*
// gets interpreted by duckdb and drops the gist index for a btree
CREATE INDEX IF NOT EXISTS idx_buildings_combined_geometry
ON brewgis.staging.buildings_combined USING GIST (geometry);
ANALYZE brewgis.staging.buildings_combined;
*/

-- Combined Building Footprints — spatial dedup union of Overture Maps
-- and VIDA (Google + Microsoft) building footprints.
--
-- Dedup strategy:
--   - ALL Overture buildings are carried through (they have height,
--     levels, class metadata that VIDA lacks).
--   - VIDA buildings with bf_source IN ('google', 'microsoft') that do
--     NOT spatially overlap (>50% area) with any Overture building are
--     included.
--   - VIDA bf_source = 'openstreetmap' buildings are dropped entirely
--     — they are redundant with Overture (also OSM-derived) and have less
--     metadata.
--
-- Source tables populated by DuckDB gateway staging models:
--   brewgis.staging.overture_buildings
--   brewgis.staging.vida_combined_buildings

WITH overture_buildings AS (
    SELECT
        ob.geometry,
        ob.height,
        ob.levels,
        ob.class,
        'overture' AS source,
        NULL::text AS bf_source,
        NULL::double precision AS confidence
    FROM duckdb.staging.overture_buildings ob
),

vida_buildings AS (
    SELECT
        vb.geometry,
        NULL::double precision AS height,
        NULL::integer AS levels,
        NULL::text AS class,
        'vida' AS source,
        vb.bf_source,
        vb.confidence
    FROM duckdb.staging.vida_combined_buildings vb
    WHERE vb.bf_source IN ('google', 'microsoft')
),

-- VIDA buildings that do NOT overlap more than 50% with any Overture building
vida_deduped AS (
    SELECT
        vb.geometry,
        vb.height,
        vb.levels,
        vb.class,
        vb.source,
        vb.bf_source,
        vb.confidence
    FROM vida_buildings vb
    WHERE vb.geometry && (SELECT ST_Extent(geometry) FROM overture_buildings LIMIT 1)
      AND NOT EXISTS (
        SELECT 1
        FROM overture_buildings ob
        WHERE ST_Intersects(vb.geometry, ob.geometry)
          AND ST_Area(ST_Intersection(vb.geometry, ob.geometry))
              > 0.5 * ST_Area(vb.geometry)
        LIMIT 1
    )
)

SELECT
    geometry,
    height,
    levels,
    class,
    source,
    bf_source,
    confidence
FROM overture_buildings

UNION ALL

SELECT
    geometry,
    height,
    levels,
    class,
    source,
    bf_source,
    confidence
FROM vida_deduped;
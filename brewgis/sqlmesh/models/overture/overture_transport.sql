MODEL (
  name brewgis.@{region}.overture_transport,
  kind VIEW,
  description 'PostGIS VIEW over the Overture transportation bridge that restores SRID metadata with ST_SetSRID: Overture Maps road segments for the region.',
  column_descriptions (
    geometry = 'Road segment re-tagged as SRID 3857 (Web Mercator, meters).',
    wgs84_geometry = 'Road segment re-tagged as SRID 4326 (degrees, EPSG:4326).',
    local_geometry = 'Always NULL: the bridge does not project to the local CRS, and the intersection models derive their own local geometry.',
    surface = 'Road surface type of the first Overture road_surface entry of the segment, e.g. paved, unpaved or gravel.',
    class = 'Overture road class of the segment, e.g. motorway, primary or residential.',
    subclass = 'Overture road subclass of the segment, cast to VARCHAR.',
    width = 'Road width in meters from the first Overture width_rules entry of the segment.'
  ),
  columns (
    geometry GEOMETRY(LineString, 3857),
    wgs84_geometry GEOMETRY(LineString, 4326),
    local_geometry GEOMETRY,
    surface TEXT,
    class TEXT,
    subclass TEXT,
    width DOUBLE
  ),
  blueprints @region_blueprints()
);

-- Overture transportation — PostGIS VIEW wrapping the DuckDB bridge table with
-- real SRIDs.
--
-- The bridge (``brewgis.<region>.overture_transport_raw``) materializes the S3
-- GeoParquet read through DuckDB, and that transfer writes SRID-less WKB: every
-- geometry in the bridge lands as SRID 0 however the SELECT tagged it (see the
-- bridge's header). Anything that reads the CRS — the tile server per tile,
-- ``ST_Transform``, a registered Layer — then fails on the bridge's own column.
--
-- This VIEW restores both CRSs with ``ST_SetSRID``, the same repair
-- ``census/tiger_blocks.sql`` makes for its bridge.
--
-- The bridge indexes its own Web Mercator column (a DuckDB-gateway table is the
-- only indexable relation here, and no index can cover this VIEW's
-- ``ST_SetSRID`` expression); the intersection-point models read this VIEW for
-- values.

SELECT
    ST_SetSRID(geometry, 3857) AS geometry,
    ST_SetSRID(wgs84_geometry, 4326) AS wgs84_geometry,
    local_geometry,
    surface,
    class,
    subclass,
    width
FROM brewgis.@{region}.overture_transport_raw;

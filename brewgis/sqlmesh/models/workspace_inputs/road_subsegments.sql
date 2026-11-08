MODEL (
  name brewgis.@{workspace_schema}.road_subsegments,
  kind VIEW,
  description 'PostGIS VIEW over the Overture subsegment bridge that restores SRID metadata with ST_SetSRID: one row per consecutive drivable connector pair, geometry in EPSG:4326.',
  column_descriptions (
    segment_id = 'Overture transport segment id this subsegment belongs to.',
    from_connector_id = 'Connector id at the subsegment start.',
    from_at = 'Fraction along the segment (0..1) of the start connector.',
    to_connector_id = 'Connector id at the subsegment end.',
    to_at = 'Fraction along the segment (0..1) of the end connector.',
    wgs84_geometry = 'Subsegment line re-tagged as SRID 4326 (degrees, EPSG:4326); the road network models project it to the local CRS.'
  ),
  columns (
    segment_id TEXT,
    from_connector_id TEXT,
    from_at DOUBLE,
    to_connector_id TEXT,
    to_at DOUBLE,
    wgs84_geometry GEOMETRY(LineString, 4326)
  ),
  blueprints @workspace_blueprints()
);

-- Overture road subsegments — PostGIS VIEW wrapping the DuckDB bridge table
-- with a real SRID.
--
-- The bridge is the workspace's ``road_subsegments_input``: its Overture read
-- (workspace_inputs/road_subsegments_fetch_raw.sql) or its package's subsegments
-- (workspace_inputs/road_subsegments_package_raw.sql) — one VIEW over either, for
-- the reason workspace_inputs/constraint_layers.sql gives. Both land through
-- DuckDB, and that transfer writes SRID-less WKB:
-- every geometry in the bridge lands as SRID 0 however the SELECT tagged it (see
-- the bridge's header). Anything that reads the CRS — a tile server transforming
-- a source per tile, ``ST_Transform``, a registered Layer — then fails on the
-- bridge's own column.
--
-- This VIEW restores the SRID with ``ST_SetSRID``, the same repair
-- ``census/tiger_blocks.sql`` makes for its bridge; ``road_network_vertices`` and
-- ``road_network_edges`` read it to build the workspace road graph.

SELECT
    segment_id,
    from_connector_id,
    from_at,
    to_connector_id,
    to_at,
    ST_SetSRID(wgs84_geometry, 4326) AS wgs84_geometry
FROM brewgis.@{workspace_schema}.@{road_subsegments_input};

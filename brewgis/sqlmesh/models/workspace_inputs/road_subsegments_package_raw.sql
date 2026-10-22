MODEL (
  name brewgis.@{workspace_schema}.road_subsegments_package_raw,
  kind FULL,
  description 'Drivable road subsegments shipped in the workspace package (the exporting workspace''s Overture read), materialized in PostGIS by DuckDB: one row per consecutive connector pair, geometry in EPSG:4326 landing as SRID 0.',
  column_descriptions (
    segment_id = 'Overture transport segment id this subsegment belongs to',
    from_connector_id = 'Connector id at the subsegment start',
    from_at = 'Fraction along the segment (0..1) of the start connector',
    to_connector_id = 'Connector id at the subsegment end',
    to_at = 'Fraction along the segment (0..1) of the end connector',
    wgs84_geometry = 'Subsegment geometry in EPSG:4326 stored as SRID 0; the published road_subsegments VIEW re-tags it, and the road network models project it to the workspace CRS.'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    segment_id VARCHAR,
    from_connector_id VARCHAR,
    from_at DOUBLE,
    to_connector_id VARCHAR,
    to_at DOUBLE,
    wgs84_geometry GEOMETRY
  ),
  blueprints @workspace_blueprints('package_public_data')
);

-- Packaged road subsegments — the same contract as the Overture bridge
-- (workspace_inputs/road_subsegments_fetch_raw.sql), read from the
-- ``road_subsegments`` part of the package when it shipped its public data
-- (``Workspace.public_data_source = package``). ``road_subsegments`` and the
-- road network models read this bridge whatever its source.

SELECT
    segment_id::VARCHAR AS segment_id,
    from_connector_id::VARCHAR AS from_connector_id,
    from_at::DOUBLE AS from_at,
    to_connector_id::VARCHAR AS to_connector_id,
    to_at::DOUBLE AS to_at,
    ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry
FROM read_parquet(@road_subsegments_parquet);

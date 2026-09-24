MODEL (
  name brewgis.@{region}.overture_road_subsegments,
  kind FULL,
  description 'PostGIS bridge materializing the DuckDB overture_road_subsegments VIEW: one row per consecutive drivable connector pair, geometry tagged EPSG:4326.',
  column_descriptions (
    segment_id = 'Overture transport segment id this subsegment belongs to',
    from_connector_id = 'Connector id at the subsegment start',
    from_at = 'Fraction along the segment (0..1) of the start connector',
    to_connector_id = 'Connector id at the subsegment end',
    to_at = 'Fraction along the segment (0..1) of the end connector',
    wgs84_geometry = 'Segment geometry tagged EPSG:4326; transformed to the local CRS by the road network models'
  ),
  gateway duckdb,
  blueprints @region_blueprints()
);

-- NOTE: Audits intentionally omitted (gateway duckdb) — row-count coverage of
-- the road graph is enforced by assert_row_count_between on the region
-- road_network_edges model instead.

-- Bridge that materializes the DuckDB VIEW (which reads GeoParquet from S3)
-- into the PostGIS table road_network_vertices / road_network_edges read.
-- DuckDB ST_Transform with always_xy=true already produces (lon, lat) for
-- 4326, so this only re-tags the CRS.

SELECT
    segment_id,
    from_connector_id,
    from_at,
    to_connector_id,
    to_at,
    ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry
FROM duckdb.@{region}.overture_road_subsegments;

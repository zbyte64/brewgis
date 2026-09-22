MODEL (
  name brewgis.@{region}.overture_transport,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Overture transportation VIEW, one row per road segment, with CRS tags set and local_geometry left NULL.',
  column_descriptions (
    geometry = 'Road segment geometry tagged EPSG:3857, reused from the DuckDB overture_transport view.',
    wgs84_geometry = 'Road segment geometry tagged EPSG:4326, reused from the DuckDB overture_transport view.',
    local_geometry = 'Always NULL here: local_geometry is computed downstream in the PostGIS intersection models.',
    surface = 'Road surface type carried through from the DuckDB overture_transport view.',
    class = 'Overture road class carried through from the DuckDB overture_transport view.',
    subclass = 'Overture road subclass carried through from the DuckDB overture_transport view.',
    width = 'Road width in meters carried through from the DuckDB overture_transport view.'
  ),
  gateway duckdb,
  blueprints @region_blueprints()
);

-- NOTE: Audits intentionally omitted (gateway duckdb). Transport row-count
-- coverage is enforced by assert_row_count_between on the region
-- overture_intersection_points models (min_rows := 50000).

-- Overture Transportation — bridge model that materializes the DuckDB VIEW
-- (which reads GeoParquet from S3) into a PostGIS-accessible table.
--
-- DuckDB ST_Transform with always_xy=true produces (lon,lat) for 4326
-- and (x,y) for 3857 — no axis flip needed.
-- local_geometry is computed in downstream PostGIS intersection models
-- to avoid DuckDB geographic→projected transform issues.

SELECT
    ST_SetCRS(geometry, 'EPSG:3857') AS geometry,
    ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry,
    NULL::geometry AS local_geometry,
    surface,
    class,
    subclass,
    width
FROM duckdb.@{region}.overture_transport;

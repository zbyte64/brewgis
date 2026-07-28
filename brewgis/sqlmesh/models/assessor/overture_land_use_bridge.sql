MODEL (
  name brewgis.staging.overture_land_use,
  kind FULL,
  gateway duckdb
);

-- Overture Land Use — bridge model that materializes the DuckDB VIEW
-- into a PostGIS-accessible table.
--
-- DuckDB ST_Transform with always_xy=true produces (lon,lat) for 4326
-- and (x,y) for 3857 — no axis flip needed.

SELECT
    ST_SetCRS(geometry, 'EPSG:3857') AS geometry,
    ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry,
    ST_Area(wgs84_geometry) AS area,
    subtype,
    class
FROM duckdb.staging.overture_land_use;

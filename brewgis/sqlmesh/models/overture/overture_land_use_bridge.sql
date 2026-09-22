MODEL (
  name brewgis.@{region}.overture_land_use,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Overture land use VIEW, one row per land use polygon, with CRS tags set and the WGS84 polygon area carried along.',
  column_descriptions (
    geometry = 'Land use polygon tagged EPSG:3857 (Web Mercator), reused from the DuckDB overture_land_use view.',
    wgs84_geometry = 'Land use polygon tagged EPSG:4326 (lon/lat), reused from the DuckDB overture_land_use view.',
    area = 'ST_Area of the EPSG:4326 land use polygon (square degrees).',
    subtype = 'Overture land use subtype carried through from the DuckDB overture_land_use view.',
    class = 'Overture land use class carried through from the DuckDB overture_land_use view.'
  ),
  gateway duckdb,
  blueprints @region_blueprints()
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
FROM duckdb.@{region}.overture_land_use;

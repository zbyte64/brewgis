MODEL (
  name brewgis.@{region}.overture_land_use_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Overture land use VIEW, one row per land use geometry, carrying the WGS84 area and landing every geometry as SRID 0.',
  column_descriptions (
    geometry = 'Land use geometry in EPSG:3857 (Web Mercator) stored as SRID 0; the published overture_land_use VIEW re-tags it.',
    wgs84_geometry = 'Land use geometry in EPSG:4326 (lon/lat) stored as SRID 0; the published overture_land_use VIEW re-tags it.',
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
--
-- The DuckDB-to-PostGIS transfer writes SRID-less WKB, so the ``ST_SetCRS``
-- calls below do not survive it: both geometry columns land as SRID 0 (measured
-- against this stack; the probe is recorded in ``osm/food_pois_raw.sql``). The
-- published ``brewgis.<region>.overture_land_use`` VIEW is what restores the two
-- CRSs with ``ST_SetSRID``.

SELECT
    ST_SetCRS(geometry, 'EPSG:3857') AS geometry,
    ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry,
    ST_Area(wgs84_geometry) AS area,
    subtype,
    class
FROM duckdb.@{region}.overture_land_use;

-- NOTE: no post_statements — this model runs through DuckDB, and DuckDB cannot
-- create a PostGIS index on its attached table ("Only altering tables is
-- supported for now"). The published ``brewgis.<region>.overture_land_use`` is a
-- PostGIS model instead: it materializes this bridge with both CRSs tagged and
-- carries the GiST/BTREE indexes the parcel lookup needs.

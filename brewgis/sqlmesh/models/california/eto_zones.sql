MODEL (
  name brewgis.california.eto_zones,
  kind VIEW,
  description 'PostGIS VIEW over the Reference Evapotranspiration Zones bridge that restores SRID metadata with ST_SetSRID.',
  column_descriptions (
    eto_zone = 'Reference Evapotranspiration Zone number (1-18) the polygon belongs to; the zone a parcel falls in is the one whose polygon contains its centroid.',
    annual_eto_in = 'Annual reference evapotranspiration of the zone (inches per year), the sum of its twelve monthly average ETo depths.',
    geometry = 'Zone boundary re-tagged as SRID 4326 (degrees, EPSG:4326) and normalized to MultiPolygon.'
  ),
  columns (
    eto_zone INTEGER,
    annual_eto_in DOUBLE,
    geometry GEOMETRY(MultiPolygon, 4326)
  )
);

-- California Reference Evapotranspiration Zones — PostGIS VIEW wrapping the
-- DuckDB bridge with a real SRID.
--
-- The bridge (brewgis.california.eto_zones_raw) materializes the fetched zones
-- through DuckDB, and that transfer writes SRID-less WKB. This VIEW restores the
-- SRID with ST_SetSRID and normalizes the geometry kind with ST_Multi (the
-- published layer mixes Polygon and MultiPolygon features — 391 Polygon to 1
-- MultiPolygon when this was written).
--
-- Consumers must index ST_SetSRID(geometry, 4326) on the *bridge* table, not the
-- bare column: the FDW inlines this VIEW's expression (see
-- assessor/parcel_block_groups.sql).

SELECT
    eto_zone,
    annual_eto_in,
    ST_Multi(ST_SetSRID(geometry, 4326)) AS geometry
FROM brewgis.california.eto_zones_raw;

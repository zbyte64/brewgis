MODEL (
  name brewgis.california.building_climate_zones,
  kind VIEW,
  description 'PostGIS VIEW over the Title-24 Building Climate Zones bridge that restores SRID metadata with ST_SetSRID.',
  column_descriptions (
    title24_zone = 'Building Climate Zone number (1-16) the polygon belongs to; the CEC Title-24 zone a parcel falls in is the zone whose polygon contains its centroid.',
    geometry = 'Zone boundary re-tagged as SRID 4326 (degrees, EPSG:4326) and normalized to MultiPolygon.'
  ),
  columns (
    title24_zone INTEGER,
    geometry GEOMETRY(MultiPolygon, 4326)
  )
);

-- California Building Climate Zones — PostGIS VIEW wrapping the DuckDB bridge
-- with a real SRID.
--
-- The bridge (brewgis.california.building_climate_zones_raw) materializes the
-- fetched zones through DuckDB, and that transfer writes SRID-less WKB: every
-- geometry lands in the bridge as SRID 0 however the SELECT tagged it. Anything
-- that reads the CRS — a spatial predicate, a tile server transforming a source
-- per tile, a layer registration — then fails on the bridge's own column.
--
-- This VIEW restores the SRID with ST_SetSRID, the repair census/tiger_blocks
-- makes for its own bridge, and normalizes the geometry kind with ST_Multi: the
-- published layer mixes Polygon and MultiPolygon features (11 MultiPolygon to 5
-- Polygon when this was written), and the declared column type is MultiPolygon.
--
-- Consumers that join parcels to these zones must index
-- ST_SetSRID(geometry, 4326) on the *bridge* table, not the bare column: the
-- FDW inlines this VIEW's expression, so a GiST index on
-- building_climate_zones_raw.geometry is never used by the consumer's predicate
-- (see assessor/parcel_block_groups.sql, which carries that index for its own
-- bridge).

SELECT
    title24_zone,
    ST_Multi(ST_SetSRID(geometry, 4326)) AS geometry
FROM brewgis.california.building_climate_zones_raw;

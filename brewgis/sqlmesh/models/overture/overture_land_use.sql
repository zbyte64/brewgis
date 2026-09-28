MODEL (
  name brewgis.@{region}.overture_land_use,
  kind FULL,
  description 'PostGIS materialization of the Overture land use bridge with both CRSs tagged and the indexes the parcel lookup needs: Overture Maps land use geometry for the region.',
  column_descriptions (
    geometry = 'Land use geometry tagged SRID 3857 (Web Mercator, meters); the source subtype carries lines and polygons.',
    wgs84_geometry = 'Land use geometry tagged SRID 4326 (degrees, EPSG:4326).',
    area = 'ST_Area of the EPSG:4326 land use geometry (square degrees), carried through from the bridge.',
    subtype = 'Overture land use subtype, carried through from the bridge.',
    class = 'Overture land use class, carried through from the bridge.'
  ),
  columns (
    geometry GEOMETRY(GEOMETRY, 3857),
    wgs84_geometry GEOMETRY(GEOMETRY, 4326),
    area DOUBLE,
    subtype TEXT,
    class TEXT
  ),
  blueprints @region_blueprints()
);

-- Overture land use — PostGIS table copied from the DuckDB bridge with real
-- SRIDs and the indexes ``overture_land_use_parcel`` needs.
--
-- The bridge (``brewgis.<region>.overture_land_use_raw``) materializes the S3
-- GeoParquet read through DuckDB, and that transfer writes SRID-less WKB: every
-- geometry in the bridge lands as SRID 0 however the SELECT tagged it (see the
-- bridge's header). Anything that reads the CRS — the tile server per tile,
-- ``ST_Transform``, a registered Layer — then fails on the bridge's own column.
--
-- This model restores both CRSs with ``ST_SetSRID``, the same repair
-- ``census/tiger_blocks.sql`` makes in a VIEW. It is a materialized table rather
-- than a VIEW because its predicate columns must be indexed, and neither the
-- bridge (DuckDB cannot create a PostGIS index) nor a VIEW (not indexable, and
-- an index cannot cover an ``ST_SetSRID`` expression) can carry one — the same
-- reason ``buildings/combined_pg.sql`` exists next to ``buildings_combined``.
--
-- Consequence for consumers: this table's columns carry their real CRS, so a
-- spatial predicate can be written directly against ``wgs84_geometry`` and use
-- the GiST index below — no ``ST_SetSRID`` wrapper, and no SRID-0 stand-in.

SELECT
    ST_SetSRID(geometry, 3857) AS geometry,
    ST_SetSRID(wgs84_geometry, 4326) AS wgs84_geometry,
    area,
    subtype,
    class
FROM brewgis.@{region}.overture_land_use_raw;

-- post_statements
-- ``overture_land_use_parcel`` index-scans ``wgs84_geometry`` for the parcels
-- its centroid test misses, and orders the candidates by ``area``. The advisory
-- lock serializes concurrent plans building this snapshot.
  DO $$ BEGIN PERFORM pg_advisory_xact_lock(hashtext('idx_overture_land_use_wgs84_geometry')::bigint); END $$;
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_overture_land_use_wgs84_geometry_')
  ON @this_model USING GIST (wgs84_geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_overture_land_use_area_')
  ON @this_model USING BTREE (area);
  ANALYZE @this_model;

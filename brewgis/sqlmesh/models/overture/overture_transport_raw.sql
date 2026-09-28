MODEL (
  name brewgis.@{region}.overture_transport_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Overture transportation VIEW, one row per road segment, with local_geometry left NULL and every geometry landing as SRID 0.',
  column_descriptions (
    geometry = 'Road segment geometry in EPSG:3857 stored as SRID 0; the published overture_transport VIEW re-tags it.',
    wgs84_geometry = 'Road segment geometry in EPSG:4326 stored as SRID 0; the published overture_transport VIEW re-tags it.',
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
--
-- The DuckDB-to-PostGIS transfer writes SRID-less WKB, so the ``ST_SetCRS``
-- calls below do not survive it: both geometry columns land as SRID 0 (measured
-- against this stack; the probe is recorded in ``osm/food_pois_raw.sql``). The
-- published ``brewgis.<region>.overture_transport`` VIEW restores the two CRSs
-- with ``ST_SetSRID``, while the intersection-point models index *this* table
-- (their GiST indexes are created here because a DuckDB-gateway table is the
-- only indexable relation in the chain).

SELECT
    ST_SetCRS(geometry, 'EPSG:3857') AS geometry,
    ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry,
    NULL::geometry AS local_geometry,
    surface,
    class,
    subclass,
    width
FROM duckdb.@{region}.overture_transport;

-- NOTE: no post_statements — this model runs through DuckDB, and DuckDB cannot
-- create a PostGIS index on its attached table ("Only altering tables is
-- supported for now"). The consumers read the published VIEW for values and
-- filter it by road class, which needs no spatial index.

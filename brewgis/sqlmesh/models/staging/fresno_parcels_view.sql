MODEL (
  name brewgis.staging.fresno_parcels,
  kind VIEW,
  columns (
    parcel_id TEXT,
    apn TEXT,
    agency_cod TEXT,
    roll_year TEXT,
    shape_area DOUBLE PRECISION,
    geometry GEOMETRY(GEOMETRY, 4326)
  )
);

-- Fresno Parcels — PostGIS VIEW wrapping the DuckDB bridge table with
-- proper SRID column metadata.
--
-- The DuckDB bridge (brewgis.staging._fresno_parcels_raw) materializes the
-- fetched parcels with ST_SetCRS, then SQLMesh exposes it to PostGIS via
-- FDW. However, the FDW drops SRID metadata, so all geometries arrive as
-- SRID=0.
--
-- This VIEW restores SRID 4326 via ST_SetSRID so parcel_shim's existing
-- ST_Transform(geometry, @default_srid) is an identity transform instead of
-- erroring on SRID 0, and downstream spatial predicates can use the indexed
-- geometry column directly.

SELECT
    parcel_id,
    apn,
    agency_cod,
    roll_year,
    shape_area,
    ST_SetSRID(geometry, 4326) AS geometry
FROM brewgis.staging._fresno_parcels_raw;

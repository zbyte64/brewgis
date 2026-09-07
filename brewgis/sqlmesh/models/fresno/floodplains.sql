MODEL (
  name brewgis.fresno.floodplains,
  kind VIEW,
  columns (
    fld_zone TEXT,
    sfha_tf TEXT,
    static_bfe DOUBLE PRECISION,
    geom GEOMETRY(GEOMETRY, 4326)
  )
);

-- Fresno Floodplains — PostGIS VIEW wrapping the DuckDB bridge table with
-- proper SRID column metadata.
--
-- The DuckDB bridge (brewgis.staging._fresno_floodplains_raw) materializes
-- the fetched FEMA NFHL flood zones with ST_SetCRS, then SQLMesh exposes it
-- to PostGIS via FDW. The FDW drops SRID metadata, so all geometries arrive
-- as SRID=0.
--
-- This VIEW restores SRID 4326 via ST_SetSRID and renames the geometry column
-- to geom (the convention expected by constraint discounting).

SELECT
    fld_zone,
    sfha_tf,
    static_bfe,
    ST_SetSRID(geometry, 4326) AS geom
FROM brewgis.staging._fresno_floodplains_raw;

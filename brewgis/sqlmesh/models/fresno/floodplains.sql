MODEL (
  name brewgis.fresno.floodplains,
  kind VIEW,
  description 'FEMA NFHL flood zones over the Fresno region from MapServer layer 28, one polygon per row.',
  column_descriptions (
    fld_zone = 'FEMA flood hazard zone code (FLD_ZONE) of the polygon in the NFHL layer.',
    sfha_tf = 'SFHA_TF flag marking whether the zone is a Special Flood Hazard Area.',
    static_bfe = 'STATIC_BFE static base flood elevation from the NFHL record (source units, not rescaled).',
    geom = 'Flood zone polygon at SRID 4326, restored with ST_SetSRID from the bridge table geometry.'
  ),
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
-- The DuckDB bridge (brewgis.fresno.floodplains_raw) materializes
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
FROM brewgis.fresno.floodplains_raw;

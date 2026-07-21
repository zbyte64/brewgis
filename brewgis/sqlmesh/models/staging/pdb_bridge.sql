MODEL (
  name brewgis.staging.pdb_bridge,
  kind FULL,
  gateway duckdb
);

-- PDB Raw Bridge — materializes the DuckDB VIEW (which reads from Census API)
-- into a PostGIS-accessible table so downstream PostGIS models can reference
-- it via cross-gateway reads.
--
-- Replaces the public.pdb_raw table previously created by the dlt pdb pipeline.
-- All columns match the dlt staging schema in pdb.py:dlt.resource(columns=...).

SELECT * FROM duckdb.staging.pdb_raw;

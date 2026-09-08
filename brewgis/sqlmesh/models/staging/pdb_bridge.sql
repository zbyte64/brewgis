MODEL (
  name brewgis.@{region}.pdb_bridge,
  kind FULL,
  gateway duckdb,
  blueprints (
    (region := sacog),
    (region := fresno)
  )
);

-- PDB Raw Bridge — materializes the DuckDB VIEW (which reads from Census API)
-- into a PostGIS-accessible table so downstream PostGIS models can reference
-- it via cross-gateway reads.
--
-- Replaces the public.pdb_raw table previously created by the dlt pdb pipeline.
-- All columns match the dlt staging schema in pdb.py:dlt.resource(columns=...).

SELECT * FROM duckdb.@{region}.pdb_raw;

MODEL (
  name brewgis.analysis.total_ghg,
  kind FULL,
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- G3 — Total GHG Summary
--
-- Aggregates transportation (G1) and building/water (G2) emissions into
-- a per-parcel summary.
--
-- Dependencies: transport_ghg (G1), building_water_ghg (G2)

SELECT
    COALESCE(t.parcel_id, b.parcel_id) AS parcel_id,
    COALESCE(t.co2e_total_kg, 0.0) AS co2e_transport,
    COALESCE(b.co2e_energy_total_kg, 0.0) AS co2e_buildings,
    COALESCE(b.co2e_water_total_kg, 0.0) AS co2e_water,
    COALESCE(t.co2e_total_kg, 0.0)
    + COALESCE(b.co2e_total_kg, 0.0) AS co2e_total
FROM brewgis.analysis.transport_ghg AS t
FULL OUTER JOIN brewgis.analysis.building_water_ghg AS b
    ON t.parcel_id = b.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_total_ghg_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;

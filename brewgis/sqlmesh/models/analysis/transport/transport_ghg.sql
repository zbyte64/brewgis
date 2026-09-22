MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  blueprints @analysis_blueprints('transport_ghg'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- G1 — Transportation GHG
--
-- Computes greenhouse gas emissions (CO2e) from vehicle miles traveled.
-- VMT x emission factor (kg CO2e per mile), with optional speed adjustment.
--
-- Variables:
--   @transport_ghg_co2_per_mile: CO2e per mile (default: 0.411 kg/mi — EPA fleet avg).
--   @transport_ghg_speed_adjust: Enable speed-based emission adjustment (bool, default: false).

WITH vmt_data AS (
    SELECT
        v.parcel_id,
        v.vmt_total,
        v.avg_trip_length_mi,
        v.auto_trips,
        es.pop,
        es.geometry
    FROM @{scenario_schema}.vmt AS v
    LEFT JOIN @{scenario_schema}.core_end_state AS es
        ON v.parcel_id = es.parcel_id
)

SELECT
    parcel_id,

    -- CO2e total (kg): VMT x emission factor, with optional speed adjustment
    vmt_total * @transport_ghg_co2_per_mile
    * CASE WHEN @transport_ghg_speed_adjust THEN 1.15 ELSE 1.0 END
        AS co2e_total_kg,

    -- CO2e per capita
    CASE
        WHEN pop > 0
        THEN (
            vmt_total * @transport_ghg_co2_per_mile
            * CASE WHEN @transport_ghg_speed_adjust THEN 1.15 ELSE 1.0 END
        ) / pop
        ELSE 0.0
    END AS co2e_per_capita_kg,

    vmt_total,
    avg_trip_length_mi,
    auto_trips,
    geometry
FROM vmt_data;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_transport_ghg_geometry_')
  ON @this_model USING GIST (geometry);

  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_transport_ghg_parcel_id_')
  ON @this_model USING btree (parcel_id);


-- Publish this model's result view where the Layers, Martin and UI paths read
-- it. The view selects from this model's prod virtual view (never its physical
-- table), so promoting a non-prod environment never repoints it. See
-- sqlmesh/macros/analysis_blueprints.py.
ON_VIRTUAL_UPDATE_BEGIN;

CREATE SCHEMA IF NOT EXISTS "@{result_schema}";

CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS
SELECT * FROM @{scenario_schema}."@{model_table}";

ON_VIRTUAL_UPDATE_END;

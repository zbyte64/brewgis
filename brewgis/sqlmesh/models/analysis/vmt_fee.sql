MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  blueprints @analysis_blueprints('vmt_fee'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- VMT Mitigation Fee Calculator
--
-- Multiplies scenario VMT by configurable fee rates ($/VMT) and tracks
-- exempt VMT and forgone revenue. Implements SB 743 VMT mitigation fee
-- programs (e.g. Fresno's $295/VMT fee with partial exemptions).
--
-- Variables:
--   @vmt_fee_rate_dollars_per_vmt: Fee rate per VMT (default: 295.0).
--   @vmt_exempt_pct: Percentage of VMT exempt from fee (default: 0.0).

WITH vmt_data AS (
    SELECT
        v.parcel_id,
        es.area_gross_acres,
        es.pop,
        es.hh,
        v.vmt_total,
        v.vmt_per_capita,
        v.geometry
    FROM @{scenario_schema}.vmt AS v
    LEFT JOIN @{scenario_schema}.core_end_state AS es
        ON v.parcel_id = es.parcel_id
)
SELECT
    parcel_id,
    area_gross_acres,
    pop,
    hh,
    vmt_total,
    @vmt_fee_rate_dollars_per_vmt AS fee_rate_dollars_per_vmt,
    ROUND((vmt_total * @vmt_exempt_pct / 100.0)::numeric, 2) AS vmt_exempt,
    -- Fee revenue on non-exempt VMT
    ROUND((vmt_total * (1.0 - @vmt_exempt_pct / 100.0) * @vmt_fee_rate_dollars_per_vmt)::numeric, 2) AS fee_revenue_total,
    -- Forgone revenue from exempt VMT
    ROUND((vmt_total * @vmt_exempt_pct / 100.0 * @vmt_fee_rate_dollars_per_vmt)::numeric, 2) AS revenue_forgone,
    -- Net revenue after exemption
    ROUND((vmt_total * (1.0 - @vmt_exempt_pct / 100.0) * @vmt_fee_rate_dollars_per_vmt)::numeric, 2) AS net_revenue,
    geometry
FROM vmt_data;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_vmt_fee_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_vmt_fee_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;


-- Publish this model's result view where the Layers, Martin and UI paths read
-- it. The view selects from this model's prod virtual view (never its physical
-- table), so promoting a non-prod environment never repoints it. See
-- sqlmesh/macros/analysis_blueprints.py.
ON_VIRTUAL_UPDATE_BEGIN;

CREATE SCHEMA IF NOT EXISTS "@{result_schema}";

CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS
SELECT * FROM @{scenario_schema}."@{model_table}";

ON_VIRTUAL_UPDATE_END;

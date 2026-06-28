MODEL (
  name brewgis.analysis.vmt_fee,
  kind FULL,
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
        es.gross_acres,
        es.population,
        es.households,
        v.vmt_total,
        v.vmt_per_capita,
        v.geom
    FROM brewgis.analysis.vmt AS v
    LEFT JOIN brewgis.analysis.core_end_state AS es
        ON v.parcel_id = es.parcel_id
)
SELECT
    parcel_id,
    gross_acres,
    population,
    households,
    vmt_total,
    @vmt_fee_rate_dollars_per_vmt AS fee_rate_dollars_per_vmt,
    ROUND((vmt_total * @vmt_exempt_pct / 100.0)::numeric, 2) AS vmt_exempt,
    -- Fee revenue on non-exempt VMT
    ROUND((vmt_total * (1.0 - @vmt_exempt_pct / 100.0) * @vmt_fee_rate_dollars_per_vmt)::numeric, 2) AS fee_revenue_total,
    -- Forgone revenue from exempt VMT
    ROUND((vmt_total * @vmt_exempt_pct / 100.0 * @vmt_fee_rate_dollars_per_vmt)::numeric, 2) AS revenue_forgone,
    -- Net revenue after exemption
    ROUND((vmt_total * (1.0 - @vmt_exempt_pct / 100.0) * @vmt_fee_rate_dollars_per_vmt)::numeric, 2) AS net_revenue,
    geom
FROM vmt_data;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_vmt_fee_geom
  ON @this_model USING GIST (geom);
  CREATE INDEX IF NOT EXISTS idx_vmt_fee_parcel_id
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;

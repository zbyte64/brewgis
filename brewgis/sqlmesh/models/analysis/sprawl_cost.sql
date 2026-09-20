MODEL (
  name brewgis.analysis.sprawl_cost,
  kind FULL,
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- Cost of Sprawl per Household
--
-- Divides scenario infrastructure costs (service costs + capital costs)
-- by number of households to compute cost per household.
--
-- Variables:
--   @sprawl_infrastructure_cost_per_du: Annual infrastructure cost per DU (default: 15000).
--   @sprawl_capital_cost_per_du: One-time capital cost per DU (default: 50000).

WITH parcel_data AS (
    SELECT
        es.parcel_id,
        es.area_gross_acres,
        es.pop,
        es.hh,
        es.du,
        es.geometry,
        es.land_development_category,
        es.built_form_key,
        -- Infrastructure cost: annual service cost + amortized capital cost
        ROUND((es.du * @sprawl_infrastructure_cost_per_du)::numeric, 2) AS infrastructure_cost_annual,
        ROUND((es.du * @sprawl_capital_cost_per_du)::numeric, 2) AS capital_cost
    FROM brewgis.analysis.core_end_state AS es
)
SELECT
    parcel_id,
    area_gross_acres,
    pop,
    hh,
    du,
    built_form_key,
    @sprawl_infrastructure_cost_per_du AS infrastructure_cost_per_du_annual,
    @sprawl_capital_cost_per_du AS capital_cost_per_du,
    infrastructure_cost_annual,
    capital_cost,
    -- Infrastructure cost per household (annual)
    ROUND(
        (infrastructure_cost_annual + capital_cost / 30.0)  -- 30-year amortization
        / NULLIF(hh, 0)::numeric, 2
    ) AS infrastructure_cost_per_hh_annual,
    geometry
FROM parcel_data;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_sprawl_cost_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_sprawl_cost_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;

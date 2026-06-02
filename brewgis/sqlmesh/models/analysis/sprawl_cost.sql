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
        es.gross_acres,
        es.population,
        es.households,
        es.dwelling_units_total,
        es.geom,
        es.land_dev_category,
        -- Infrastructure cost: annual service cost + amortized capital cost
        ROUND((es.dwelling_units_total * @sprawl_infrastructure_cost_per_du)::numeric, 2) AS infrastructure_cost_annual,
        ROUND((es.dwelling_units_total * @sprawl_capital_cost_per_du)::numeric, 2) AS capital_cost
    FROM brewgis.analysis.core_end_state AS es
)
SELECT
    parcel_id,
    gross_acres,
    population,
    households,
    dwelling_units_total,
    @sprawl_infrastructure_cost_per_du AS infrastructure_cost_per_du_annual,
    @sprawl_capital_cost_per_du AS capital_cost_per_du,
    infrastructure_cost_annual,
    capital_cost,
    -- Infrastructure cost per household (annual)
    ROUND(
        (infrastructure_cost_annual + capital_cost / 30.0)  -- 30-year amortization
        / NULLIF(households, 0)::numeric, 2
    ) AS infrastructure_cost_per_hh_annual,
    geom
FROM parcel_data

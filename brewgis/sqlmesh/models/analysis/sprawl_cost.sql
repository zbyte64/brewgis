MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel cost of sprawl: infrastructure and amortised capital cost per unit and household.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    pop = 'Population allocated to the parcel (people).',
    hh = 'Households allocated to the parcel (households).',
    du = 'Dwelling units allocated to the parcel (units).',
    built_form_key = 'Built form key assigned to the parcel in the end state.',
    infrastructure_cost_per_du_annual = 'Annual infrastructure cost per dwelling unit ($ per unit per year).',
    capital_cost_per_du = 'One-time capital cost per dwelling unit ($ per unit).',
    infrastructure_cost_annual = 'Annual infrastructure cost of the parcel ($ per year).',
    capital_cost = 'One-time capital cost of the parcel ($).',
    infrastructure_cost_per_hh_annual = 'Infrastructure plus amortised capital cost per household ($ per year).',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('sprawl_cost'),
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
    FROM @{scenario_schema}.core_end_state AS es
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


-- Publish this model's result view where the Layers, Martin and UI paths read
-- it. The view selects from this model's prod virtual view (never its physical
-- table), so promoting a non-prod environment never repoints it. See
-- sqlmesh/macros/analysis_blueprints.py.
ON_VIRTUAL_UPDATE_BEGIN;

CREATE SCHEMA IF NOT EXISTS "@{result_schema}";

CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS
SELECT * FROM @{scenario_schema}."@{model_table}";

ON_VIRTUAL_UPDATE_END;

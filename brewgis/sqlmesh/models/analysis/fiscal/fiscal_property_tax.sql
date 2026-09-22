MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  blueprints @analysis_blueprints('fiscal_property_tax'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- F1 — Property Tax Revenue
--
-- Computes property tax revenue from assessed value of residential and
-- non-residential development.
--
-- Formula:
--   assessed_value_res = dwelling_units_total x res_assessed_value_per_du
--   assessed_value_nonres = building_sqft_total x nonres_assessed_value_per_sqft
--   property_tax_revenue = (assessed_value_res + assessed_value_nonres)
--                          x property_tax_rate / 100
--
-- Variables:
--   @res_assessed_value_per_du: Assessed value per dwelling unit (default: 350000).
--   @nonres_assessed_value_per_sqft: Assessed value per sqft non-res (default: 150).
--   @property_tax_rate: Property tax rate in percent (default: 1.0).

SELECT
    es.parcel_id,
    -- Residential assessed value
    COALESCE(es.du * @res_assessed_value_per_du, 0.0) AS assessed_value_res,
    -- Non-residential assessed value
    COALESCE(es.building_sqft_total * @nonres_assessed_value_per_sqft, 0.0) AS assessed_value_nonres,
    -- Property tax revenue
    COALESCE(
        (es.du * @res_assessed_value_per_du
         + es.building_sqft_total * @nonres_assessed_value_per_sqft)
        * @property_tax_rate / 100.0,
        0.0
    ) AS property_tax_revenue,
    es.geometry
FROM @{scenario_schema}.core_end_state AS es;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_fiscal_property_tax_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_fiscal_property_tax_parcel_id_')
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

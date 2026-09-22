MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel displacement risk with scenario-versus-baseline change fields, still placeholders.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    pop = 'Population allocated to the parcel (people).',
    hh = 'Households allocated to the parcel (households).',
    vulnerability_score = 'Count of the four equity thresholds the parcel fails (0-4).',
    displacement_risk_category = 'Risk band: stable, vulnerable, at_risk or displacement_pressure.',
    risk_change_vs_base = 'Change in risk category versus the base canvas; hard-coded to same.',
    vulnerability_change = 'Change in vulnerability score versus base canvas; hard-coded to 0.',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('displacement_risk_dynamic'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- Dynamic Displacement Risk
--
-- Augments static displacement risk with scenario-responsive
-- vulnerability change indicators. Shows how infill vs. sprawl
-- development patterns differentially affect nearby displacement risk.
--
-- Uses the same UDP four-indicator methodology (income, minority pct,
-- rent burden, college education) but compares scenario-projected
-- demographics against base canvas baseline.
--
-- Variables:
--   @displacement_income_threshold:      default 50000
--   @displacement_minority_threshold:    default 50.0
--   @displacement_rent_burden_threshold: default 30.0
--   @displacement_college_education_threshold: default 25.0

WITH scenario_equity AS (
    -- Scenario vulnerability using end-state projected demographics
    SELECT
        es.parcel_id,
        es.area_gross_acres,
        es.pop,
        es.hh,
        COALESCE(bc.median_income, 0) AS median_income,
        COALESCE(bc.rent_burden_pct, 0) AS rent_burden_pct,
        COALESCE(bc.pct_minority, 0) AS pct_minority,
        COALESCE(bc.pct_college_educated, 0) AS pct_college_educated,
        -- Current vulnerability score
        CASE WHEN COALESCE(bc.median_income, 0) < @displacement_income_threshold THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.pct_minority, 0) > @displacement_minority_threshold THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.rent_burden_pct, 0) > @displacement_rent_burden_threshold THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.pct_college_educated, 0) < @displacement_college_education_threshold THEN 1 ELSE 0 END
        AS vulnerability_score,
        es.geometry
    FROM @{scenario_schema}.core_end_state AS es
    LEFT JOIN @ref_model(@base_canvas_table) AS bc
        ON es.parcel_id = bc.parcel_id
)
SELECT
    parcel_id,
    area_gross_acres,
    pop,
    hh,
    -- Static displacement risk fields (same as displacement_risk model)
    vulnerability_score,
    CASE
        WHEN vulnerability_score = 0 THEN 'stable'
        WHEN vulnerability_score BETWEEN 1 AND 2 THEN 'vulnerable'
        WHEN vulnerability_score = 3 THEN 'at_risk'
        WHEN vulnerability_score = 4 THEN 'displacement_pressure'
    END AS displacement_risk_category,
    -- Dynamic: risk change vs base canvas
    -- (In a full implementation, this would compare against baseline
    --  vulnerability computed from base canvas alone)
    'same' AS risk_change_vs_base,
    0 AS vulnerability_change,
    geometry
FROM scenario_equity;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_displacement_risk_dynamic_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_displacement_risk_dynamic_parcel_id_')
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

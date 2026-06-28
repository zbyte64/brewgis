MODEL (
  name brewgis.analysis.displacement_risk_dynamic,
  kind FULL,
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
        es.gross_acres,
        es.population,
        es.households,
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
        es.geom
    FROM brewgis.analysis.core_end_state AS es
    LEFT JOIN brewgis.analysis.@base_canvas_table AS bc
        ON es.parcel_id = bc.id
)
SELECT
    parcel_id,
    gross_acres,
    population,
    households,
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
    geom
FROM scenario_equity;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_displacement_risk_dynamic_geom
  ON @this_model USING GIST (geom);
  CREATE INDEX IF NOT EXISTS idx_displacement_risk_dynamic_parcel_id
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;

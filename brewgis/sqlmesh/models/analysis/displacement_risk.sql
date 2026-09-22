MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  blueprints @analysis_blueprints('displacement_risk'),
);

WITH parcel_equity AS (
    SELECT
        es.parcel_id,
        es.area_gross_acres,
        es.pop,
        es.hh,
        bc.median_income,
        bc.rent_burden_pct,
        bc.pct_minority,
        bc.pct_college_educated,
        es.geometry,
        -- Vulnerability indicators (each TRUE adds 1 point)
        CASE WHEN COALESCE(bc.median_income, 0) < @displacement_income_threshold THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.pct_minority, 0) > @displacement_minority_threshold THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.rent_burden_pct, 0) > @displacement_rent_burden_threshold THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.pct_college_educated, 0) < @displacement_college_education_threshold THEN 1 ELSE 0 END
        AS vulnerability_score
    FROM @{scenario_schema}.core_end_state AS es
    LEFT JOIN @ref_model(@base_canvas_table) AS bc
        ON es.parcel_id = bc.parcel_id
)

SELECT
    parcel_id,
    area_gross_acres,
    pop,
    hh,
    median_income,
    rent_burden_pct,
    pct_minority,
    pct_college_educated,
    vulnerability_score,
    -- Displacement risk category
    CASE
        WHEN vulnerability_score = 0 THEN 'stable'
        WHEN vulnerability_score BETWEEN 1 AND 2 THEN 'vulnerable'
        WHEN vulnerability_score = 3 THEN 'at_risk'
        WHEN vulnerability_score = 4 THEN 'displacement_pressure'
    END AS displacement_risk_category,
    geometry
FROM parcel_equity;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_displacement_risk_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_displacement_risk_parcel_id_')
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

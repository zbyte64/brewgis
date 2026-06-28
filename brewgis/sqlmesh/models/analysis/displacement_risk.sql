MODEL (
  name brewgis.analysis.displacement_risk,
  kind FULL,
);

WITH parcel_equity AS (
    SELECT
        es.parcel_id,
        es.gross_acres,
        es.population,
        es.households,
        bc.median_income,
        bc.rent_burden_pct,
        bc.pct_minority,
        bc.pct_college_educated,
        es.geom,
        -- Vulnerability indicators (each TRUE adds 1 point)
        CASE WHEN COALESCE(bc.median_income, 0) < @displacement_income_threshold THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.pct_minority, 0) > @displacement_minority_threshold THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.rent_burden_pct, 0) > @displacement_rent_burden_threshold THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.pct_college_educated, 0) < @displacement_college_education_threshold THEN 1 ELSE 0 END
        AS vulnerability_score
    FROM brewgis.analysis.core_end_state AS es
    LEFT JOIN brewgis.analysis.base_canvas AS bc
        ON es.parcel_id = bc.id
)

SELECT
    parcel_id,
    gross_acres,
    population,
    households,
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
    geom
FROM parcel_equity;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_displacement_risk_geom
  ON @this_model USING GIST (geom);
  CREATE INDEX IF NOT EXISTS idx_displacement_risk_parcel_id
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;

MODEL (
  name brewgis.tests.stage_test_parcels,
  kind VIEW,
  audits (
    not_null(columns := (parcel_id))
  )
);

WITH raw AS (
    SELECT * FROM brewgis.seeds.test_parcels
)
SELECT

    -- Map detected ID column to parcel_id and id
    parcel_id AS parcel_id,
    parcel_id AS id,
    2 AS built_form_key,  -- SFR Standard default
    CASE
        WHEN ST_Area(geometry) / 4046.86 > 0
            THEN LEAST(25.0, GREATEST(0.5, 10.0 / SQRT(ST_Area(geometry) / 4046.86)))
        ELSE 0.5
    END AS intersection_density,
    'standard' AS land_development_category,
    geometry AS geom,
    land_use,
    NULL::FLOAT AS acres
FROM raw

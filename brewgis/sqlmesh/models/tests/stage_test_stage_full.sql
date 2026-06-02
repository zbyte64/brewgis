MODEL (
  name brewgis.tests.stage_test_stage_full,
  kind VIEW,
  audits (
    not_null(columns := (id))
  )
);

WITH raw AS (
    SELECT * FROM brewgis.seeds.test_base_canvas
)
SELECT

    -- Map detected ID column to parcel_id and id
    id AS parcel_id,
    id AS id,
    built_form_key,
    intersection_density,
    land_development_category,
    geometry AS geom
FROM raw

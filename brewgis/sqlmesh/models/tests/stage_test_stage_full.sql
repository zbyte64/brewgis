MODEL (
  name brewgis.tests.stage_test_stage_full,
  kind VIEW,
  description 'Test fixture: staging VIEW selecting identity, built form and geometry from the test_base_canvas seed.',
  column_descriptions (
    parcel_id = 'Parcel identifier carried through from the test_base_canvas seed.',
    built_form_key = 'Built form key carried through from the test_base_canvas seed.',
    intersection_density = 'Intersection density carried through from the test_base_canvas seed (per km2).',
    land_development_category = 'Land development category carried through from the test_base_canvas seed.',
    geom = 'Parcel geometry from the test_base_canvas seed (EPSG:4326).'
  ),
  audits (
    not_null(columns := (parcel_id))
  )
);

WITH raw AS (
    SELECT * FROM brewgis.seeds.test_base_canvas
)
SELECT

    -- Map detected ID column to parcel_id
    parcel_id,
    built_form_key,
    intersection_density,
    land_development_category,
    geometry AS geom
FROM raw

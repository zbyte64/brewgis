MODEL (
  name brewgis.tests.stage_test_parcels,
  kind VIEW,
  description 'Test fixture: staging VIEW mapping the test_parcels seed into the staged parcel shape.',
  column_descriptions (
    parcel_id = 'Parcel identifier mapped from the detected id column of the test_parcels seed.',
    built_form_key = 'Built form key, hard-coded to 2 (standard single-family residential) here.',
    intersection_density = 'Intersection density (per km2) from gross area in acres, clamped to 0.5 to 25.',
    land_development_category = 'Land development category, hard-coded to standard for every parcel here.',
    geom = 'Parcel geometry from the test_parcels seed (EPSG:4326).',
    land_use = 'Land use value carried through from the test_parcels seed.',
    acres = 'Parcel area in acres, always null in this fixture.'
  ),
  audits (
    not_null(columns := (parcel_id))
  )
);

WITH raw AS (
    SELECT * FROM brewgis.seeds.test_parcels
)
SELECT

    -- Map detected ID column to parcel_id
    parcel_id AS parcel_id,
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

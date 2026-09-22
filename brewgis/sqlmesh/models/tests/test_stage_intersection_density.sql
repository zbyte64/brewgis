MODEL (
  name brewgis.tests.test_stage_intersection_density,
  kind VIEW,
  description 'Test fixture: staging VIEW matching the overture_intersection_density schema from test lot size.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) of the test parcel.',
    intersection_density = 'Proxy intersection density (per km2) from lot size, clamped between 0.5 and 50.',
    geometry = 'Parcel geometry from the test assessor parcels seed (EPSG:4326).'
  ),
  audits (
    not_null(columns := (apn))
  )
);

-- Test staging model: produces output matching overture_intersection_density schema
-- from the test_assessor_parcels seed data, using a proxy density calculation.

SELECT
    apn,
    CASE
        WHEN NULLIF(lotsize, 0) IS NOT NULL AND lotsize > 0
        THEN GREATEST(0.5, LEAST(50.0, 15.0 / SQRT(lotsize)))
        ELSE 0.5
    END::double precision AS intersection_density,
    geometry
FROM brewgis.seeds.test_assessor_parcels;

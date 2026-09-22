MODEL (
  name brewgis.tests.test_stage_assessor_parcels,
  kind VIEW,
  description 'Test fixture: staging VIEW matching the sacog_assessor_parcels schema from the test seed.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) of the test parcel.',
    geometry = 'Parcel geometry from the test seed (EPSG:4326).',
    lot_size_acres = 'Parcel lot size (acres), with zero lots replaced by a 0.01 acre floor.',
    landuse = 'Assessor land use code of the parcel.',
    zone = 'Assessor zoning designation of the parcel.',
    jurisdiction = 'Jurisdiction code the parcel sits in.'
  ),
  audits (
    not_null(columns := (apn))
  )
);

-- Test staging model: produces output matching sacog_assessor_parcels schema
-- from the test_assessor_parcels seed data.

SELECT
    apn,
    geometry,
    COALESCE(NULLIF(lotsize, 0), 0.01)::double precision AS lot_size_acres,
    landuse,
    zone,
    jurisdiction
FROM brewgis.seeds.test_assessor_parcels;

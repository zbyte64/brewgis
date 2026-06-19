MODEL (
  name brewgis.tests.test_stage_assessor_parcels,
  kind VIEW,
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

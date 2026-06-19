MODEL (
  name brewgis.tests.test_stage_sales,
  kind VIEW,
  audits (
    not_null(columns := (apn))
  )
);

-- Test staging model: produces output matching sacog_assessor_sales_raw schema
-- from the test_assessor_sales seed data.

SELECT
    apn,
    living_area::double precision AS living_area,
    building_sf::double precision AS building_sf,
    year_built::integer AS year_built,
    stories::double precision AS stories,
    bedrooms::integer AS bedrooms,
    baths::double precision AS baths,
    ground_floor_gross::double precision AS ground_floor_gross,
    land_use_code,
    property_type,
    sales_price::double precision AS sales_price,
    lot_size_acres::double precision AS lot_size_acres,
    units::integer AS units
FROM brewgis.seeds.test_assessor_sales;

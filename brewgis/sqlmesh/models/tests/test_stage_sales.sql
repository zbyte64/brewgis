MODEL (
  name brewgis.tests.test_stage_sales,
  kind VIEW,
  description 'Test fixture: staging VIEW matching the sacog_assessor_sales_raw schema from the test seed.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) the sale belongs to.',
    living_area = 'Living area of the structure (sq ft).',
    building_sf = 'Total building square footage of the structure (sq ft).',
    year_built = 'Year the structure was built (calendar year).',
    stories = 'Number of stories in the structure (stories).',
    bedrooms = 'Number of bedrooms in the structure (count).',
    baths = 'Number of bathrooms in the structure (count, fractional for partial baths).',
    ground_floor_gross = 'Gross ground floor area of the structure (sq ft).',
    land_use_code = 'Assessor land use code of the parcel.',
    property_type = 'Assessor property type of the parcel.',
    sales_price = 'Recorded sale price of the parcel ($).',
    lot_size_acres = 'Parcel lot size (acres).',
    units = 'Number of dwelling units on the parcel (count).'
  ),
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

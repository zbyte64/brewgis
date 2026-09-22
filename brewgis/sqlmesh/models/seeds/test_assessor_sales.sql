MODEL (
  name brewgis.seeds.test_assessor_sales,
  kind SEED (
    path '../../seeds/test_assessor_sales.csv'
  ),
  description 'Test fixture: 30 assessor sales rows for the test_stage_sales staging view unit test.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) the sale belongs to.',
    living_area = 'Living area of the sold structure (sq ft).',
    building_sf = 'Total building square footage of the sold structure (sq ft).',
    year_built = 'Year the sold structure was built.',
    stories = 'Number of stories in the sold structure.',
    bedrooms = 'Number of bedrooms in the sold structure.',
    baths = 'Number of bathrooms in the sold structure.',
    ground_floor_gross = 'Gross ground floor area of the sold structure (sq ft).',
    land_use_code = 'Assessor land use code of the sold parcel.',
    property_type = 'Assessor property type of the sold parcel (e.g. SFR).',
    sales_price = 'Recorded sale price of the transaction ($).',
    lot_size_acres = 'Lot size of the sold parcel (acres).',
    units = 'Number of dwelling units in the sold property.'
  ),
  columns (
    apn TEXT,
    living_area DOUBLE PRECISION,
    building_sf DOUBLE PRECISION,
    year_built INTEGER,
    stories DOUBLE PRECISION,
    bedrooms INTEGER,
    baths DOUBLE PRECISION,
    ground_floor_gross DOUBLE PRECISION,
    land_use_code TEXT,
    property_type TEXT,
    sales_price DOUBLE PRECISION,
    lot_size_acres DOUBLE PRECISION,
    units INTEGER
  )
);

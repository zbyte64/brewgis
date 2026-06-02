MODEL (
  name brewgis.seeds.test_assessor_sales,
  kind SEED (
    path '../../seeds/test_assessor_sales.csv'
  ),
  columns (
    apn TEXT,
    living_area DOUBLE PRECISION,
    building_sf DOUBLE PRECISION,
    year_built TEXT,
    stories TEXT,
    bedrooms TEXT,
    baths TEXT,
    ground_floor_gross TEXT,
    land_use_code TEXT,
    property_type TEXT,
    sales_price DOUBLE PRECISION,
    lot_size_acres DOUBLE PRECISION,
    units TEXT
  )
);

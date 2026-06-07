MODEL (
  name brewgis.seeds.test_assessor_sales,
  kind SEED (
    path '../../seeds/test_assessor_sales.csv'
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

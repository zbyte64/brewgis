MODEL (
  name duckdb.sacog.assessor_sales,
  kind VIEW,
  description 'DuckDB staging view of Sacramento County assessor sales read from the local GeoParquet cache.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) of the sold property.',
    living_area = 'Total living area of the sold building (sq ft).',
    building_sf = 'Total building square footage reported by the assessor for the sold property (sq ft).',
    year_built = 'Effective year the sold building was built.',
    stories = 'Number of stories in the sold building.',
    bedrooms = 'Number of bedrooms in the sold building.',
    baths = 'Number of bathrooms in the sold building.',
    ground_floor_gross = 'Gross ground-floor area reported by the assessor for the sold building.',
    land_use_code = 'Assessor land-use code of the sold parcel.',
    property_type = 'Assessor property type of the sold property.',
    sales_price = 'Indicated sale price reported by the Sacramento County assessor sales layer.',
    lot_size_acres = 'Lot size of the sold parcel (acres).',
    units = 'Number of units reported by the assessor for the sold property (count).'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    apn VARCHAR,
    living_area DOUBLE,
    building_sf DOUBLE,
    year_built INTEGER,
    stories DOUBLE,
    bedrooms INTEGER,
    baths DOUBLE,
    ground_floor_gross DOUBLE,
    land_use_code VARCHAR,
    property_type VARCHAR,
    sales_price DOUBLE,
    lot_size_acres DOUBLE,
    units INTEGER
  )
);

-- Sacramento County assessor sales/building characteristics — DuckDB reads
-- from local GeoParquet.
--
-- The GeoParquet file is created by assessor_fetcher.write_to_geoparquet(),
-- which downloads sales data from ArcGIS REST services.

SELECT * FROM read_parquet('/app/planning/assessor/assessor_sales.parquet');

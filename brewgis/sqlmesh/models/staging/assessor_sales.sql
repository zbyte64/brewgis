MODEL (
  name duckdb.staging.assessor_sales,
  kind VIEW,
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

MODEL (
  name brewgis.sacog.assessor_sales_raw,
  kind FULL,
  description 'Assessor sales bridge: materializes the DuckDB staging view duckdb.sacog.assessor_sales into PostGIS.',
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
  gateway duckdb
);

-- Assessor Sales Bridge — materializes the DuckDB VIEW (which reads from
-- local GeoParquet) into a PostGIS-accessible table.
--
-- Replaces the public.sacog_assessor_sales_raw table previously created
-- by the dlt assessor pipeline.

SELECT * FROM duckdb.sacog.assessor_sales;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_sacog_assessor_sales_raw_apn_')
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_sacog_assessor_sales_raw_property_type_')
  ON @this_model USING btree (property_type);

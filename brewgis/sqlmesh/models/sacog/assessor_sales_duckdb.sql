MODEL (
  name duckdb.sacog.assessor_sales,
  kind VIEW,
  description 'DuckDB staging VIEW reading the Sacramento County Sales by Property Type MapServer (ASSESSOR/MapServer/1) through arcgis_query, one row per APN.',
  column_descriptions (
    apn = 'Assessor parcel number (APN, the layer''s PARCEL_NUMBER) of the sold property.',
    living_area = 'Total living area of the sold building (TOTAL_LIVING_AREA, sq ft).',
    building_sf = 'Total building square footage reported by the assessor for the sold property (BUILDING_SF, sq ft).',
    year_built = 'Effective year the sold building was built (EFFECTIVE_YEAR_BUILT).',
    stories = 'Number of stories in the sold building (NUMBER_OF_STORIES).',
    bedrooms = 'Number of bedrooms in the sold building (NUMBER_OF_BEDROOMS).',
    baths = 'Number of bathrooms in the sold building (NUMBER_OF_BATHS).',
    ground_floor_gross = 'Gross ground-floor area reported by the assessor for the sold building (GROUND_FLOOR_GROSS).',
    land_use_code = 'Assessor land-use code of the sold parcel (LAND_USE_CODE).',
    property_type = 'Assessor property type of the sold property (Property_Type).',
    sales_price = 'Indicated sale price reported by the Sacramento County assessor sales layer (INDICATED_SALES_PRICE, dollars).',
    lot_size_acres = 'Lot size of the sold parcel (LOT_SIZE_ACRES, acres).',
    units = 'Number of units reported by the assessor for the sold property (Units, count).'
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

-- Sacramento County assessor sales/building characteristics — DuckDB VIEW over
-- the county's Sales by Property Type layer (ASSESSOR/MapServer/1). arcgis_query
-- (the arcgis extension) pages through the whole layer and returns its fields
-- as typed columns; the geometry is never selected, so it is not requested.
--
-- The layer can carry several sales per PARCEL_NUMBER; one row per APN is kept,
-- preferring the record with both TOTAL_LIVING_AREA and BUILDING_SF present,
-- then the latest EFFECTIVE_YEAR_BUILT (OBJECTID breaks ties
-- deterministically). INDICATED_SALES_PRICE is published as text holding a
-- decimal amount ('250000.0000'), hence the cast.

SELECT
  PARCEL_NUMBER AS apn,
  TOTAL_LIVING_AREA::DOUBLE AS living_area,
  BUILDING_SF AS building_sf,
  EFFECTIVE_YEAR_BUILT::INTEGER AS year_built,
  NUMBER_OF_STORIES AS stories,
  NUMBER_OF_BEDROOMS::INTEGER AS bedrooms,
  NUMBER_OF_BATHS AS baths,
  GROUND_FLOOR_GROSS AS ground_floor_gross,
  LAND_USE_CODE AS land_use_code,
  Property_Type AS property_type,
  INDICATED_SALES_PRICE::DOUBLE AS sales_price,
  LOT_SIZE_ACRES AS lot_size_acres,
  Units AS units
FROM arcgis_query('https://mapservices.gis.saccounty.net/arcgis/rest/services/ASSESSOR/MapServer/1')
WHERE length(trim(PARCEL_NUMBER)) > 0
QUALIFY row_number() OVER (
  PARTITION BY PARCEL_NUMBER
  ORDER BY
    (TOTAL_LIVING_AREA IS NOT NULL)::INTEGER + (BUILDING_SF IS NOT NULL)::INTEGER DESC,
    EFFECTIVE_YEAR_BUILT DESC NULLS LAST,
    OBJECTID
) = 1;

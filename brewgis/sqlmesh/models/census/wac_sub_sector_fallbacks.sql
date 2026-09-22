MODEL (
  name brewgis.@{region}.wac_sub_sector_fallbacks,
  kind FULL,
  description 'County-level fallback shares of employment within each WAC super-sector, summed from the block sub-sectors of wac_block, one row per county.',
  column_descriptions (
    county_fips = 'Three-digit county FIPS code the fallback shares were computed for.',
    emp_retail_services_frac = 'Retail services share of the five retail sub-sectors summed per county (fraction).',
    emp_restaurant_frac = 'Restaurant share of the five retail sub-sectors summed per county (fraction).',
    emp_accommodation_frac = 'Accommodation share of the five retail sub-sectors summed per county (fraction).',
    emp_arts_entertainment_frac = 'Arts and entertainment share of the five retail sub-sectors summed per county.',
    emp_other_services_frac = 'Other services share of the five retail sub-sectors summed per county (fraction).',
    emp_office_services_frac = 'Office services share of office plus medical employment summed per county (fraction).',
    emp_medical_services_frac = 'Medical services share of office plus medical employment summed per county.',
    emp_public_admin_frac = 'Public administration share of public administration plus education summed per county.',
    emp_education_frac = 'Education share of public administration plus education employment summed per county.',
    emp_manufacturing_frac = 'Manufacturing share of the five industrial sub-sectors summed per county (fraction).',
    emp_wholesale_frac = 'Wholesale share of the five industrial sub-sectors summed per county (fraction).',
    emp_transport_warehousing_frac = 'Transport and warehousing share of the five industrial sub-sectors per county.',
    emp_utilities_frac = 'Utilities share of the five industrial sub-sectors summed per county (fraction).',
    emp_construction_frac = 'Construction share of the five industrial sub-sectors summed per county (fraction).',
    emp_agriculture_frac = 'Agricultural share of agriculture plus extraction employment summed per county.',
    emp_extraction_frac = 'Extraction share of agriculture plus extraction employment summed per county (fraction).'
  ),
  grain (county_fips),
  blueprints @region_blueprints()
);

WITH wac_sub_sector_totals AS (
  SELECT
    @county_fips AS county_fips,
    COALESCE(SUM(emp_retail_services), 0)   AS total_emp_retail_services,
    COALESCE(SUM(emp_restaurant), 0)         AS total_emp_restaurant,
    COALESCE(SUM(emp_accommodation), 0)      AS total_emp_accommodation,
    COALESCE(SUM(emp_arts_entertainment), 0) AS total_emp_arts_entertainment,
    COALESCE(SUM(emp_other_services), 0)     AS total_emp_other_services,
    COALESCE(SUM(emp_office_services), 0)    AS total_emp_office_services,
    COALESCE(SUM(emp_medical_services), 0)   AS total_emp_medical_services,
    COALESCE(SUM(emp_public_admin), 0)       AS total_emp_public_admin,
    COALESCE(SUM(emp_education), 0)          AS total_emp_education,
    COALESCE(SUM(emp_manufacturing), 0)      AS total_emp_manufacturing,
    COALESCE(SUM(emp_wholesale), 0)          AS total_emp_wholesale,
    COALESCE(SUM(emp_transport_warehousing), 0) AS total_emp_transport_warehousing,
    COALESCE(SUM(emp_utilities), 0)          AS total_emp_utilities,
    COALESCE(SUM(emp_construction), 0)       AS total_emp_construction,
    COALESCE(SUM(emp_agriculture), 0)        AS total_emp_agriculture,
    COALESCE(SUM(emp_extraction), 0)         AS total_emp_extraction
  FROM brewgis.@{region}.wac_block
)
SELECT
  county_fips,
  CASE WHEN total_emp_retail_services + total_emp_restaurant + total_emp_accommodation
    + total_emp_arts_entertainment + total_emp_other_services > 0
    THEN total_emp_retail_services / (total_emp_retail_services + total_emp_restaurant
      + total_emp_accommodation + total_emp_arts_entertainment + total_emp_other_services)
    ELSE 0 END AS emp_retail_services_frac,
  CASE WHEN total_emp_retail_services + total_emp_restaurant + total_emp_accommodation
    + total_emp_arts_entertainment + total_emp_other_services > 0
    THEN total_emp_restaurant / (total_emp_retail_services + total_emp_restaurant
      + total_emp_accommodation + total_emp_arts_entertainment + total_emp_other_services)
    ELSE 0 END AS emp_restaurant_frac,
  CASE WHEN total_emp_retail_services + total_emp_restaurant + total_emp_accommodation
    + total_emp_arts_entertainment + total_emp_other_services > 0
    THEN total_emp_accommodation / (total_emp_retail_services + total_emp_restaurant
      + total_emp_accommodation + total_emp_arts_entertainment + total_emp_other_services)
    ELSE 0 END AS emp_accommodation_frac,
  CASE WHEN total_emp_retail_services + total_emp_restaurant + total_emp_accommodation
    + total_emp_arts_entertainment + total_emp_other_services > 0
    THEN total_emp_arts_entertainment / (total_emp_retail_services + total_emp_restaurant
      + total_emp_accommodation + total_emp_arts_entertainment + total_emp_other_services)
    ELSE 0 END AS emp_arts_entertainment_frac,
  CASE WHEN total_emp_retail_services + total_emp_restaurant + total_emp_accommodation
    + total_emp_arts_entertainment + total_emp_other_services > 0
    THEN total_emp_other_services / (total_emp_retail_services + total_emp_restaurant
      + total_emp_accommodation + total_emp_arts_entertainment + total_emp_other_services)
    ELSE 0 END AS emp_other_services_frac,
  CASE WHEN total_emp_office_services + total_emp_medical_services > 0
    THEN total_emp_office_services / (total_emp_office_services + total_emp_medical_services)
    ELSE 0 END AS emp_office_services_frac,
  CASE WHEN total_emp_office_services + total_emp_medical_services > 0
    THEN total_emp_medical_services / (total_emp_office_services + total_emp_medical_services)
    ELSE 0 END AS emp_medical_services_frac,
  CASE WHEN total_emp_public_admin + total_emp_education > 0
    THEN total_emp_public_admin / (total_emp_public_admin + total_emp_education)
    ELSE 0 END AS emp_public_admin_frac,
  CASE WHEN total_emp_public_admin + total_emp_education > 0
    THEN total_emp_education / (total_emp_public_admin + total_emp_education)
    ELSE 0 END AS emp_education_frac,
  CASE WHEN total_emp_manufacturing + total_emp_wholesale + total_emp_transport_warehousing
    + total_emp_utilities + total_emp_construction > 0
    THEN total_emp_manufacturing / (total_emp_manufacturing + total_emp_wholesale
      + total_emp_transport_warehousing + total_emp_utilities + total_emp_construction)
    ELSE 0 END AS emp_manufacturing_frac,
  CASE WHEN total_emp_manufacturing + total_emp_wholesale + total_emp_transport_warehousing
    + total_emp_utilities + total_emp_construction > 0
    THEN total_emp_wholesale / (total_emp_manufacturing + total_emp_wholesale
      + total_emp_transport_warehousing + total_emp_utilities + total_emp_construction)
    ELSE 0 END AS emp_wholesale_frac,
  CASE WHEN total_emp_manufacturing + total_emp_wholesale + total_emp_transport_warehousing
    + total_emp_utilities + total_emp_construction > 0
    THEN total_emp_transport_warehousing / (total_emp_manufacturing + total_emp_wholesale
      + total_emp_transport_warehousing + total_emp_utilities + total_emp_construction)
    ELSE 0 END AS emp_transport_warehousing_frac,
  CASE WHEN total_emp_manufacturing + total_emp_wholesale + total_emp_transport_warehousing
    + total_emp_utilities + total_emp_construction > 0
    THEN total_emp_utilities / (total_emp_manufacturing + total_emp_wholesale
      + total_emp_transport_warehousing + total_emp_utilities + total_emp_construction)
    ELSE 0 END AS emp_utilities_frac,
  CASE WHEN total_emp_manufacturing + total_emp_wholesale + total_emp_transport_warehousing
    + total_emp_utilities + total_emp_construction > 0
    THEN total_emp_construction / (total_emp_manufacturing + total_emp_wholesale
      + total_emp_transport_warehousing + total_emp_utilities + total_emp_construction)
    ELSE 0 END AS emp_construction_frac,
  CASE WHEN total_emp_agriculture + total_emp_extraction > 0
    THEN total_emp_agriculture / (total_emp_agriculture + total_emp_extraction)
    ELSE 0 END AS emp_agriculture_frac,
  CASE WHEN total_emp_agriculture + total_emp_extraction > 0
    THEN total_emp_extraction / (total_emp_agriculture + total_emp_extraction)
    ELSE 0 END AS emp_extraction_frac
FROM wac_sub_sector_totals;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_wac_sub_sector_fallbacks_county_fips_')
  ON @this_model USING btree (county_fips);

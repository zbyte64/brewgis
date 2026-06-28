MODEL (
  name brewgis.assessor.sacog_assessor_sales_deduped,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  )
);

-- Deduplicated SACOG Assessor Sales — one row per APN with the best available
-- observation. Deduplication prioritizes rows with the most complete data,
-- then by most recent year_built.
--
-- Materialized to avoid repeating this dedup logic across 3 consumer models
-- (parcel_known_features, parcel_dasymetric_weights, authoritative_residential_area).

SELECT
    apn,
    living_area AS actual_living_sqft,
    building_sf AS actual_building_sqft,
    property_type,
    lot_size_acres AS sales_lot_size_acres,
    units
FROM (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY apn
            ORDER BY
                CASE
                    WHEN living_area IS NOT NULL AND building_sf IS NOT NULL AND units IS NOT NULL THEN 0
                    WHEN living_area IS NOT NULL THEN 1
                    WHEN building_sf IS NOT NULL THEN 2
                    ELSE 3
                END,
                year_built DESC NULLS LAST
        ) AS rn
    FROM public.sacog_assessor_sales_raw
    WHERE living_area IS NOT NULL OR building_sf IS NOT NULL
) dedup
WHERE rn = 1;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_sacog_assessor_sales_deduped_apn
  ON @this_model USING btree (apn);
ANALYZE @this_model;

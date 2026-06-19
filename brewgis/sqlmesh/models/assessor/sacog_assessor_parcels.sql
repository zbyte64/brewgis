MODEL (
  name brewgis.assessor.sacog_assessor_parcels,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,)),
    assert_sacog_assessor_parcels_row_count
  )
);

-- SACOG Assessor Parcels — parcel geometries from Sacramento County Assessor,
-- deduplicated by apn.
--
-- Reads from brewgis.assessor_parcels (populated by the assessor dlt pipeline
-- from PARCELS/MapServer/8) and produces table with validated geometry.
--
-- ArcGIS PARCELS/MapServer/8 may return multiple features per APN (multi-part
-- parcels, land-use splits, etc.). This model deduplicates by taking the row
-- with the largest lotsize per apn to provide a single canonical row per parcel.

WITH deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY apn
            ORDER BY lotsize::double precision DESC NULLS LAST
        ) AS rn
    FROM public.sacog_assessor_parcels_raw
)
SELECT
    apn,
    ST_MakeValid(geometry) AS geometry,
    ST_Centroid(ST_MakeValid(geometry)) AS centroid,
    ST_Transform(ST_MakeValid(geometry), @VAR('local_srid', 3310)) AS local_geometry,
    ST_Centroid(ST_Transform(ST_MakeValid(geometry), @VAR('local_srid', 3310))) AS centroid_local,
    lotsize::double precision AS lot_size_acres,
    landuse,
    zone,
    jurisdiction,
    COALESCE(
        auc.category,
        CASE
            WHEN landuse IS NULL OR landuse = '' THEN 'undeveloped'
            WHEN LEFT(landuse::text, 1) = 'A' THEN 'urban'
            WHEN LEFT(landuse::text, 1) = 'B' THEN 'urban'
            WHEN LEFT(landuse::text, 1) = 'C' THEN 'urban'
            WHEN LEFT(landuse::text, 1) = 'D' THEN 'undeveloped'
            WHEN LEFT(landuse::text, 1) = 'E' THEN 'urban'
            WHEN LEFT(landuse::text, 1) = 'F' THEN 'agricultural'
            WHEN LEFT(landuse::text, 1) = 'G' THEN 'undeveloped'
            WHEN LEFT(landuse::text, 1) = 'H' THEN 'urban'
            WHEN LEFT(landuse::text, 1) = 'I' THEN 'industrial'
            WHEN LEFT(landuse::text, 2) IN ('MP','MR','MW','MD','MF','MG','ML') THEN 'undeveloped'
            WHEN LEFT(landuse::text, 1) = 'M' THEN 'urban'
            WHEN LEFT(landuse::text, 1) = 'W' THEN 'undeveloped'
            ELSE 'undeveloped'
        END,
        'urban'
    ) AS land_development_category
FROM deduped
LEFT JOIN brewgis.seeds.assessor_use_codes auc
    ON LEFT(COALESCE(landuse::text, ''), 2) = auc.use_code::text
WHERE rn = 1;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_sacog_assessor_parcels_geometry
  ON brewgis.assessor.sacog_assessor_parcels USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_sacog_assessor_parcels_local_geometry
  ON brewgis.assessor.sacog_assessor_parcels USING GIST (local_geometry);
  CREATE INDEX IF NOT EXISTS idx_sacog_assessor_parcels_centroid_local
  ON brewgis.assessor.sacog_assessor_parcels USING GIST (centroid_local);
  CREATE INDEX IF NOT EXISTS idx_sacog_assessor_parcels_centroid
  ON brewgis.assessor.sacog_assessor_parcels USING GIST (centroid);
  CREATE INDEX IF NOT EXISTS idx_sacog_assessor_parcels_apn
  ON brewgis.assessor.sacog_assessor_parcels (apn);
  ANALYZE brewgis.assessor.sacog_assessor_parcels;

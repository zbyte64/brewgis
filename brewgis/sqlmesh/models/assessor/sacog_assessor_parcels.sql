MODEL (
  name brewgis.assessor.sacog_assessor_parcels,
  kind FULL,
  audits (
    not_null(columns := (apn))
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
    lotsize::double precision AS lot_size_acres,
    landuse,
    zone,
    jurisdiction
FROM deduped
WHERE rn = 1

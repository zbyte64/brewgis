{#
    SACOG Assessor Parcels — parcel geometries from Sacramento County Assessor,
    deduplicated by parcel_id.

    Reads from ``public.sacog_assessor_parcels_raw`` (populated by the assessor
    dlt pipeline from PARCELS/MapServer/8) and produces view-compatible column
    names for downstream dasymetric weight computation.

    Column mapping:
        parcel_id              → PARCEL_NUMBER (string APN)
        geometry               → PostGIS geometry (EPSG:4326)
        lot_size_acres         → LOTSIZE (reported lot size)
        landuse                → LANDUSE (6-character assessor code)
        zone                   → ZONE_ (zoning designation)
        jurisdiction           → JURISDICTION (city/county)

    ArcGIS PARCELS/MapServer/8 may return multiple features per APN (multi-part
    parcels, land-use splits, etc.). This view deduplicates by taking the row
    with the largest lotsize per parcel_id to provide a single canonical row
    per parcel for dasymetric weighting.

    Materialized as: view
#}

{{ config(materialized='view') }}

WITH deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY parcel_id
            ORDER BY lotsize::double precision DESC NULLS LAST
        ) AS rn
FROM {{ source('brewgis', 'assessor_parcels') }}
)
SELECT
    parcel_id,
    geometry,
    lotsize::double precision AS lot_size_acres,
    landuse,
    zone,
    jurisdiction
FROM deduped
WHERE rn = 1

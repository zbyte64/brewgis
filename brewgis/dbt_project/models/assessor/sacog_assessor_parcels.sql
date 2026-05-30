{#
    SACOG Assessor Parcels — parcel geometries from Sacramento County Assessor,
    deduplicated by apn.

    Reads from ``public.sacog_assessor_parcels_raw`` (populated by the assessor
    dlt pipeline from PARCELS/MapServer/8) and produces table with validated
    geometry for downstream dasymetric weight computation.

    Column mapping:
        apn                    → PARCEL_NUMBER (string APN)
        geometry               → PostGIS geometry (EPSG:4326), ST_MakeValid applied
        lot_size_acres         → LOTSIZE (reported lot size)
        landuse                → LANDUSE (6-character assessor code)
        zone                   → ZONE_ (zoning designation)
        jurisdiction           → JURISDICTION (city/county)

    ArcGIS PARCELS/MapServer/8 may return multiple features per APN (multi-part
    parcels, land-use splits, etc.). This model deduplicates by taking the row
    with the largest lotsize per parcel_id to provide a single canonical row
    per parcel for dasymetric weighting, using apn instead of parcel_id.

    Materialized as: table (was view — geometry now validated once at materialization
    rather than ST_MakeValid being applied on every downstream spatial join).
#}

{{ config(materialized='table',
    indexes=[
        {'columns': ['apn'], 'unique': True},
        {'columns': ['geometry'], 'type': 'gist'},
    ])
}}

WITH deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY apn
            ORDER BY lotsize::double precision DESC NULLS LAST
        ) AS rn
FROM {{ source('brewgis', 'assessor_parcels') }}
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

{#
    SACOG Assessor Parcels — raw parcel geometries from Sacramento County Assessor.

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

    Materialized as: view
#}

{{ config(materialized='view') }}

SELECT
    parcel_id,
    geometry,
    lotsize::double precision AS lot_size_acres,
    landuse,
    zone,
    jurisdiction
FROM {{ source('brewgis', 'assessor_parcels') }}

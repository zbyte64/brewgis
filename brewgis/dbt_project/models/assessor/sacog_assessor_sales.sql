{#
    SACOG Assessor Sales — building characteristics from Sacramento County Assessor,
    keyed by apn.

    Reads from ``public.sacog_assessor_sales_raw`` (populated by the assessor
    dlt pipeline from ASSESSOR/MapServer/1) and renames columns for
    downstream building median computation.

    Key columns:
        apn                    → APN (string, joins to parcel geometry)
        living_area            → TOTAL_LIVING_AREA (residential sqft)
        building_sf            → BUILDING_SF (total building sqft)
        year_built             → EFFECTIVE_YEAR_BUILT
        bedrooms               → NUMBER_OF_BEDROOMS
        baths                  → NUMBER_OF_BATHS
        stories                → NUMBER_OF_STORIES
        property_type          → Property_Type (SFR, Condo, MF, Comm/Ind, Vacant)
        sales_price            → INDICATED_SALES_PRICE
        lot_size_acres         → LOT_SIZE_ACRES

    Materialized as: view
#}

{{ config(materialized='view') }}

SELECT
    apn,
    living_area,
    building_sf,
    year_built,
    stories,
    bedrooms,
    baths,
    ground_floor_gross,
    land_use_code,
    property_type,
    sales_price,
    lot_size_acres,
    units
FROM {{ source('brewgis', 'assessor_sales') }}

{#
    Parcel Block Groups — spatial join assigning each assessor parcel to its
    overlapping TIGER/Line block group and tract.

    Uses DISTINCT ON to pick the block group with the largest intersection
    area for parcels that cross block group boundaries.

    Block group GEOID is 12 digits (state 2 + county 3 + tract 6 + bg 1).
    Tract GEOID is 11 digits (state 2 + county 3 + tract 6).

    Materialized as: table
        - Unique index on apn
#}

{{ config(materialized='table',
    indexes=[
        {'columns': ['apn'], 'unique': True},
        {'columns': ['block_group_geoid']},
        {'columns': ['tract_geoid']},
    ])
}}

SELECT DISTINCT ON (sap.apn)
    sap.apn,
    tbg.geoid AS block_group_geoid,
    LEFT(tbg.geoid, 11) AS tract_geoid
FROM {{ ref('sacog_assessor_parcels') }} sap
JOIN {{ source('brewgis', 'tiger_block_groups') }} tbg
    ON ST_Intersects(sap.geometry, tbg.geometry)
   AND tbg.vintage = '2023'
ORDER BY sap.apn, ST_Area(ST_Intersection(sap.geometry, tbg.geometry)) DESC

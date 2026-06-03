MODEL (
  name brewgis.assessor.parcel_block_groups,
  kind FULL,
  audits (
    not_null(columns := (apn))
  )
);

-- Parcel Block Groups — spatial join assigning each assessor parcel to its
-- overlapping TIGER/Line block group and tract.
--
-- Uses DISTINCT ON to pick the block group with the largest intersection
-- area for parcels that cross block group boundaries.

SELECT DISTINCT ON (sap.apn)
    sap.apn,
    tbg.geoid AS block_group_geoid,
    LEFT(tbg.geoid, 11) AS tract_geoid
FROM brewgis.assessor.sacog_assessor_parcels sap
JOIN public.tiger_block_groups tbg
    ON ST_Intersects(sap.geometry, tbg.geometry)
   AND tbg.vintage = '2023'
ORDER BY sap.apn, ST_Area(tbg.geometry) ASC

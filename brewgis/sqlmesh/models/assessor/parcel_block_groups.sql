MODEL (
  name brewgis.assessor.parcel_block_groups,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn, data_year),
    batch_size 50000
  ),
  audits (
    not_null(columns := (apn, data_year)),
    unique_values(columns := (apn,))
  )
);

-- Parcel Block Groups — spatial join assigning each assessor parcel to its
-- overlapping TIGER/Line block group and tract.
--
-- Uses DISTINCT ON to pick the block group with the largest intersection
-- area for parcels that cross block group boundaries.

SELECT DISTINCT ON (sap.apn)
    sap.apn,
    make_date(@tiger_vintage::int, 1, 1) AS data_year,
    tbg.geoid AS block_group_geoid,
    LEFT(tbg.geoid, 11) AS tract_geoid
FROM brewgis.assessor.sacog_assessor_parcels sap
JOIN public.tiger_block_groups tbg
    ON ST_Intersects(sap.geometry, tbg.geometry)
   AND tbg.vintage = @tiger_vintage
ORDER BY sap.apn, ST_Area(ST_Intersection(sap.geometry, tbg.geometry)) DESC

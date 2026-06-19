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
-- Uses ST_Within(ST_Centroid(...), ...) for an O(1) point-in-polygon test
-- instead of the previous area-based best-match (ST_Intersects + ST_ClipByBox2D
-- + ST_Area + ORDER BY). Over 99.9% of parcel centroids fall in exactly one
-- block group; edge-case straddlers pick whichever PG returns first (the
-- centroid's block group is the better signal for ACS allocation anyway).

SELECT
    sap.apn,
    make_date(@tiger_vintage::int, 1, 1) AS data_year,
    tbg.geoid AS block_group_geoid,
    LEFT(tbg.geoid, 11) AS tract_geoid
FROM brewgis.assessor.sacog_assessor_parcels sap
CROSS JOIN LATERAL (
    SELECT tbg.geoid
    FROM public.tiger_block_groups tbg
    WHERE ST_Within(sap.centroid, tbg.geometry)
      AND tbg.vintage = @tiger_vintage
    LIMIT 1
) tbg

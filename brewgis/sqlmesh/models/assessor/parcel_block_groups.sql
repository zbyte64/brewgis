MODEL (
  name brewgis.@{region}.parcel_block_groups,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn, data_year),
    batch_size 50000
  ),
  audits (
    not_null(columns := (apn, data_year)),
    unique_values(columns := (apn,))
  ),
  depends_on (
    brewgis.census.tiger_block_groups_raw
  ),
  blueprints @region_blueprints()
);

-- pre_statements
-- GiST expression index on the bridge table's geometry column, so the
-- CROSS JOIN LATERAL ST_Within below can use an index scan instead of a sequential
-- scan across all 16.9K block group rows for each parcel (measured: >1h for a single
-- 50K-parcel batch without it).
--
-- The expression must match the consumer's predicate exactly. The
-- brewgis.census.tiger_block_groups view inlines ST_SetSRID(wgs84_geometry, 4326)
-- (the FDW drops SRID metadata), so an index on the bare column is never used, and
-- the index cannot be declared in the bridge model's own post_statements: that model
-- is duckdb-gateway, so its statements are bound and executed by DuckDB, which has no
-- ST_SetSRID — only plain column DDL such as its geoid btree index reaches PostGIS.
--
-- The name is version-scoped via @snapshot_hash, and kept short because SQLMesh
-- appends a suffix (e.g. _schema_tmp) for some migrations: Postgres caps identifiers
-- at 63 characters. Index names are scoped to the schema, not the table, so a fixed
-- name makes CREATE INDEX IF NOT EXISTS a no-op for every bridge snapshot after the
-- first: the statement then keeps "succeeding" while the snapshot backing the model
-- view has no geometry index at all.
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_tiger_bg_bridge_wgs84_geom_')
  ON brewgis.census.tiger_block_groups_raw USING GIST (ST_SetSRID(wgs84_geometry, 4326));

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
FROM brewgis.@{region}.assessor_parcels sap
CROSS JOIN LATERAL (
    SELECT tbg.geoid
    FROM brewgis.census.tiger_block_groups tbg
    WHERE ST_Within(sap.centroid, tbg.wgs84_geometry)
      AND tbg.vintage = @tiger_vintage
    LIMIT 1
) tbg;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_parcel_block_groups_apn_')
  ON @this_model USING btree (apn);
ANALYZE @this_model;

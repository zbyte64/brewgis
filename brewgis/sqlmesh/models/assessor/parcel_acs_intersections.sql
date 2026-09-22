MODEL (
  name brewgis.@{region}.parcel_acs_intersections,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn, bg_geoid),
    batch_size 100000
  ),
  description 'Intersection areas between assessor parcels and ACS block groups, one row per pair.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) of the intersecting parcel.',
    bg_geoid = 'Census block group GEOID (12-digit FIPS) of the intersecting block group.',
    hh = 'Households in the intersecting block group (count), passed through from ACS.',
    du = 'Dwelling units in the intersecting block group (count), passed through from ACS.',
    intersect_area_sqft = 'Area of the parcel and block group intersection in local_srid 3310 (metres squared).'
  ),
  audits (
    not_null(columns := (apn, bg_geoid))
  ),
  blueprints @region_blueprints()
);

-- Parcel × ACS Block Group Intersections — pre-computed intersection areas.
--
-- Extracts the expensive spatial join (ST_Intersects + ST_Intersection) from
-- parcel_du_estimation into a separate model that runs once per pipeline build
-- instead of recomputing for every plan.
--
-- Relies on brewgis.@{region}.acs_block_group_projected for pre-projected ACS
-- geometry (local_srid 3310) with a GiST index, avoiding the unindexed nested
-- loop from joining against the DuckDB-built staging table directly.
--
-- Uses ST_Intersection on local_srid (California Albers) for accurate
-- area-weighted ACS household size computation.

SELECT
    sap.apn,
    a.geoid AS bg_geoid,
    a.hh,
    a.du,
    ST_Area(ST_Intersection(
        sap.local_geometry,
        a.geometry
    )) AS intersect_area_sqft
FROM brewgis.@{region}.assessor_parcels sap
JOIN brewgis.@{region}.acs_block_group_projected a
    ON ST_Intersects(sap.local_geometry, a.geometry);

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_parcel_acs_intersections_apn_')
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_parcel_acs_intersections_bg_geoid_')
  ON @this_model USING btree (bg_geoid);
ANALYZE @this_model;

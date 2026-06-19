MODEL (
  name brewgis.assessor.parcel_acs_intersections,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn, bg_geoid),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn, bg_geoid))
  )
);

-- Parcel × ACS Block Group Intersections — pre-computed intersection areas.
--
-- Extracts the expensive spatial join (ST_Intersects + ST_Intersection) from
-- parcel_du_estimation into a separate model that runs once per pipeline build
-- instead of recomputing for every plan.
--
-- Relies on brewgis.assessor.acs_block_group_projected for pre-projected ACS
-- geometry (local_srid 3310) with a GiST index, avoiding the unindexed nested
-- loop from joining against the DuckDB-built staging table directly.
--
-- Uses ST_Intersection on local_srid (California Albers) for accurate
-- area-weighted ACS household size computation.

WITH parcels_projected AS (
    SELECT
        apn,
        ST_Transform(geometry, @VAR('local_srid', 3310)) AS geometry
    FROM brewgis.assessor.sacog_assessor_parcels
)
SELECT
    sap.apn,
    a.geoid AS bg_geoid,
    a.hh,
    a.du,
    ST_Area(ST_Intersection(
        sap.geometry,
        a.geometry
    )) AS intersect_area_sqft
FROM parcels_projected sap
JOIN brewgis.assessor.acs_block_group_projected a
    ON ST_Intersects(sap.geometry, a.geometry);

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_acs_intersections_apn
  ON brewgis.assessor.parcel_acs_intersections (apn);
ANALYZE brewgis.assessor.parcel_acs_intersections;

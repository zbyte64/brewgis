MODEL (
  name brewgis.@{region}.parcel_building_sqft_by_type,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  ),
  dialect postgres,
  blueprints (
    (region := sacog),
    (region := fresno)
  )
);

-- Region Parcel Building Square Footage by Type — per-parcel total building
-- sqft broken into Overture-derived buckets (residential, commercial,
-- industrial, other).
--
-- Pass-through of the region's building-footprint pipeline. Overture/VIDA
-- building data is global (bbox-filtered at the DuckDB staging VIEWs), so
-- every region — including Fresno — computes real building sqft from
-- ``@{region}.parcel_building_footprints``.

SELECT
    apn,
    total_footprint_sqft,
    building_count,
    footprint_ratio,
    lot_size_acres,
    COALESCE(overture_residential_sqft, 0)::double precision AS residential_building_sqft,
    COALESCE(overture_commercial_sqft, 0)::double precision AS commercial_building_sqft,
    COALESCE(overture_industrial_sqft, 0)::double precision AS industrial_building_sqft,
    COALESCE(overture_other_sqft, 0)::double precision AS other_building_sqft,
    residential_building_count,
    non_residential_building_count,
    max_levels,
    land_development_category,
    geometry
FROM brewgis.@{region}.parcel_building_footprints;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_@{region}_bldg_sqft_by_type_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS idx_@{region}_bldg_sqft_by_type_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
ANALYZE @this_model;

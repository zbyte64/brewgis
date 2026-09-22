MODEL (
  name brewgis.@{region}.parcel_building_sqft_by_type,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  description 'Per-parcel building floor area (sq ft) from the Overture/VIDA footprint pipeline, one row per APN.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) the building row belongs to.',
    total_footprint_sqft = 'Total building floor area on the parcel (sq ft = footprint x levels x overlap share).',
    building_count = 'Number of Overture and deduplicated VIDA buildings on the parcel.',
    footprint_ratio = 'Total building floor area divided by parcel lot area (ratio 0-1).',
    lot_size_acres = 'Parcel lot size from the assessor parcel row (acres).',
    residential_building_sqft = 'Floor area of buildings in Overture residential classes (sq ft); 0 when none.',
    commercial_building_sqft = 'Overture commercial and mixed-use ground-floor floor area (sq ft); 0 when none.',
    industrial_building_sqft = 'Floor area of buildings in Overture industrial classes (sq ft); 0 when none.',
    other_building_sqft = 'Floor area of buildings in the remaining Overture classes (sq ft); 0 when none.',
    residential_building_count = 'Number of buildings in Overture residential classes.',
    non_residential_building_count = 'Number of buildings outside the Overture residential classes.',
    max_levels = 'Maximum floor count among the buildings on the parcel (levels).',
    land_development_category = 'Land development category of the parcel, from the assessor use code prefix.',
    geometry = 'Parcel boundary geometry (EPSG:4326) from the assessor parcel row.'
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  ),
  dialect postgres,
  blueprints @region_blueprints()
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
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_bldg_sqft_by_type_apn_')
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_bldg_sqft_by_type_geometry_')
  ON @this_model USING GIST (geometry);
ANALYZE @this_model;

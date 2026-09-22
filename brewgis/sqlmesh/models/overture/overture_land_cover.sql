MODEL (
  name duckdb.@{region}.overture_land_cover,
  kind VIEW,
  description 'Overture Maps land cover polygons (ESA WorldCover derived) for the region, release 2026-08-19.0 GeoParquet read from S3 by DuckDB via httpfs.',
  column_descriptions (
    geometry = 'Land cover polygon reprojected from Overture CRS84 to Web Mercator (EPSG:3857).',
    wgs84_geometry = 'Land cover polygon reprojected from Overture CRS84 to EPSG:4326 (lon/lat).',
    local_geometry = 'Land cover polygon reprojected from Overture CRS84 to the region local CRS (EPSG:3310).',
    subtype = 'Overture land cover subtype of the ESA WorldCover derived polygon, cast to VARCHAR.'
  ),
  gateway duckdb,
  dialect duckdb,
  blueprints @region_blueprints()
);

-- Overture Maps land cover for Sacramento County, CA.
-- DuckDB reads GeoParquet directly from S3 via httpfs extension.
-- Land cover contains ESA WorldCover-derived polygons: forest, crop, grass, urban, etc.
-- Row-group filter pushdown on the bbox struct column ensures only
-- Sacramento-relevant row groups are fetched from S3.
-- Post-statements materialize the result in public.overture_land_cover in
-- PostGIS via the postgres_scanner-attached pg catalog.
--
-- Source CRS: CRS84 (lon/lat axis). Overture Maps GeoParquet via S3 httpfs.
-- ST_Transform with always_xy=true ensures (lon,lat) input axis order.

SELECT
  ST_Transform(geometry, 'CRS84', 'EPSG:3857', true) AS geometry,
  ST_Transform(geometry, 'CRS84', 'EPSG:4326', true) AS wgs84_geometry,
  ST_Transform(geometry, 'CRS84', 'EPSG:' || @VAR('local_srid', 3310)::text, true) AS local_geometry,
  subtype::VARCHAR AS subtype
FROM read_parquet(@overture_land_cover_parquet_glob)
WHERE bbox.xmin < @overture_bbox_max_x
  AND bbox.xmax > @overture_bbox_min_x
  AND bbox.ymin < @overture_bbox_max_y
  AND bbox.ymax > @overture_bbox_min_y;

MODEL (
  name duckdb.@{region}.overture_land_use,
  kind VIEW,
  description 'Overture Maps land use polygons for the region (release 2026-08-19.0 GeoParquet read from S3 by DuckDB via httpfs), reprojected to 3857, 4326 and the local CRS.',
  column_descriptions (
    geometry = 'Land use polygon reprojected from Overture CRS84 to Web Mercator (EPSG:3857).',
    wgs84_geometry = 'Land use polygon reprojected from Overture CRS84 to EPSG:4326 (lon/lat).',
    local_geometry = 'Land use polygon reprojected from Overture CRS84 to the region local CRS (local_srid).',
    subtype = 'Overture land use subtype of the polygon, cast to VARCHAR.',
    class = 'Overture land use class of the polygon, cast to VARCHAR.'
  ),
  gateway duckdb,
  dialect duckdb,
  blueprints @region_blueprints()
);

-- Overture Maps land use for Sacramento County, CA.
-- DuckDB reads GeoParquet directly from S3 via httpfs extension.
-- Land use contains polygons with subtype (agriculture, residential, industrial, etc.)
-- and optional class fields (farmland, commercial, retail, etc.).
-- Row-group filter pushdown on the bbox struct column ensures only
-- Sacramento-relevant row groups are fetched from S3.
-- Post-statements materialize the result in public.overture_land_use in
-- PostGIS via the postgres_scanner-attached pg catalog.
--
-- Source CRS: CRS84 (lon/lat axis). Overture Maps GeoParquet via S3 httpfs.
-- ST_Transform with always_xy=true ensures (lon,lat) input axis order.

SELECT
  ST_Transform(geometry, 'CRS84', 'EPSG:3857', true) AS geometry,
  ST_Transform(geometry, 'CRS84', 'EPSG:4326', true) AS wgs84_geometry,
  ST_Transform(geometry, 'CRS84', 'EPSG:' || @VAR('local_srid')::text, true) AS local_geometry,
  subtype::VARCHAR AS subtype,
  class::VARCHAR AS class
FROM read_parquet(@overture_land_use_parquet_glob)
WHERE bbox.xmin < @overture_bbox_max_x
  AND bbox.xmax > @overture_bbox_min_x
  AND bbox.ymin < @overture_bbox_max_y
  AND bbox.ymax > @overture_bbox_min_y;

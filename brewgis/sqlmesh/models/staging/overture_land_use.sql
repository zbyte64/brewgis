MODEL (
  name duckdb.@{region}.overture_land_use,
  kind VIEW,
  gateway duckdb,
  dialect duckdb,
  blueprints (
    (region := sacog,  overture_bbox_min_x := -121.87, overture_bbox_max_x := -121.01, overture_bbox_min_y := 38.02, overture_bbox_max_y := 38.74),
    (region := fresno, overture_bbox_min_x := -119.95, overture_bbox_max_x := -119.55, overture_bbox_min_y := 36.60, overture_bbox_max_y := 36.90)
  )
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
  ST_Transform(geometry, 'CRS84', 'EPSG:' || @VAR('local_srid', 3310)::text, true) AS local_geometry,
  subtype::VARCHAR AS subtype,
  class::VARCHAR AS class
FROM read_parquet(@overture_land_use_parquet_glob)
WHERE bbox.xmin < @overture_bbox_max_x
  AND bbox.xmax > @overture_bbox_min_x
  AND bbox.ymin < @overture_bbox_max_y
  AND bbox.ymax > @overture_bbox_min_y;

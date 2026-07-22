MODEL (
  name duckdb.staging.overture_transport,
  kind VIEW,
  gateway duckdb,
  dialect duckdb
);

-- Overture Maps transportation segments (roads) for Sacramento County, CA.
-- DuckDB reads GeoParquet directly from S3 via httpfs extension.
-- Transportation segments include road surface type (paved, unpaved, gravel),
-- road class (motorway, primary, residential, service, parking_aisle),
-- and optional width.
--
-- Important: The Overture transport schema stores surface and width in
-- STRUCT arrays (road_surface[], width_rules[]) with positional "between"
-- constraints. We extract the first element's value as a reasonable
-- approximation for the full segment. Most segments have a single value.
--
-- Row-group filter pushdown on the bbox struct column ensures only
-- Sacramento-relevant row groups are fetched from S3.
-- Post-statements materialize the result in public.overture_transport in
-- PostGIS via the postgres_scanner-attached pg catalog.
--
-- Source CRS: CRS84 (lon/lat axis). Overture Maps GeoParquet via S3 httpfs.
-- ST_Transform with always_xy=true ensures (lon,lat) input axis order.

SELECT
  ST_Transform(geometry, 'CRS84', 'EPSG:3857', true) AS geometry,
  ST_Transform(geometry, 'CRS84', 'EPSG:4326', true) AS wgs84_geometry,
  ST_Transform(geometry, 'CRS84', 'EPSG:' || @VAR('local_srid', 3310)::text, true) AS local_geometry,
  road_surface[1].value::VARCHAR AS surface,
  class::VARCHAR AS class,
  subclass::VARCHAR AS subclass,
  subtype::VARCHAR AS subtype,
  width_rules[1].value::DOUBLE AS width
FROM read_parquet(@overture_transport_parquet_glob)
WHERE bbox.xmin < @overture_bbox_max_x
  AND bbox.xmax > @overture_bbox_min_x
  AND bbox.ymin < @overture_bbox_max_y
  AND bbox.ymax > @overture_bbox_min_y;

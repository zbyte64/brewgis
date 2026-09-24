MODEL (
  name duckdb.@{region}.overture_road_subsegments,
  kind VIEW,
  description 'One row per consecutive Overture connector pair of each drivable transport segment, flattened from the segment connectors array; the raw edge list for the road graph.',
  column_descriptions (
    segment_id = 'Overture transport segment id this subsegment belongs to',
    from_connector_id = 'Connector id at the subsegment start',
    from_at = 'Fraction along the segment (0..1) of the start connector',
    to_connector_id = 'Connector id at the subsegment end',
    to_at = 'Fraction along the segment (0..1) of the end connector',
    wgs84_geometry = 'Segment geometry reprojected from CRS84 to EPSG:4326 (lon/lat), shared by the subsegment'
  ),
  gateway duckdb,
  dialect duckdb,
  blueprints @region_blueprints()
);

-- The road graph's raw edge list: Overture `type=segment` carries the
-- authoritative junction topology in its `connectors` array (one entry per
-- connector the segment touches, with the fraction along the segment where it
-- sits), which the previous endpoint-snapping graph discarded — segments do
-- not coincide geometrically at junctions, so that graph was mostly
-- disconnected.
--
-- One row per consecutive connector pair, flattened to scalars: the bridge
-- model materializes this into PostGIS, which has no DuckDB array type to
-- carry `connectors` across.
--
-- `len(connectors) >= 2` drops dangling segments (0 or 1 connector): they
-- carry no connectivity and never lie on a shortest path.
--
-- Row-group filter pushdown on the bbox struct column, as in
-- `overture_transport`: only region-relevant row groups are fetched from S3.

WITH seg AS (
    SELECT id, geometry, connectors
    FROM read_parquet(@overture_transport_parquet_glob)
    WHERE bbox.xmin < @overture_bbox_max_x
      AND bbox.xmax > @overture_bbox_min_x
      AND bbox.ymin < @overture_bbox_max_y
      AND bbox.ymax > @overture_bbox_min_y
      AND class IN ('motorway', 'trunk', 'primary', 'secondary', 'tertiary',
                    'residential', 'living_street', 'unclassified', 'service')
      AND len(connectors) >= 2
),
flat AS (SELECT id, unnest(connectors) AS c FROM seg),
ordered AS (SELECT id, array_agg(c ORDER BY c.at) AS cons FROM flat GROUP BY id)
SELECT
    s.id AS segment_id,
    cons[seq].connector_id AS from_connector_id,
    cons[seq].at AS from_at,
    cons[seq + 1].connector_id AS to_connector_id,
    cons[seq + 1].at AS to_at,
    ST_Transform(s.geometry, 'CRS84', 'EPSG:4326', true) AS wgs84_geometry
FROM ordered o
INNER JOIN seg s ON s.id = o.id
, unnest(range(1, len(o.cons))) AS t(seq);

# DuckDB Spatial — Hard-Won Lessons

## ST_Transform: The 4-Argument Form

**USE THIS**: `ST_Transform(geom, source_crs, dest_crs, always_xy)`

The 2-argument form `ST_Transform(ST_SetCRS(geom, 'EPSG:4326'), 'EPSG:3857')` **silently returns NaN/infinity** for geographic→projected transforms in DuckDB v1.5.4. The 4-argument form with `always_xy=true` works for all CRS pairs.

| Transform | 2-arg `ST_SetCRS`+`ST_Transform` | 4-arg `always_xy=true` |
|---|---|---|
| `4326→3857` | `(inf, inf)` ✗ | `(-13525318, 4650301)` ✓ |
| `4326→3310` | `(inf, inf)` ✗ | `(-130662, 54796)` ✓ |
| `4326→5070` | `(inf, inf)` ✗ | works ✓ |
| `4269→3857` | `(inf, inf)` ✗ | `(-13525318, 4650301)` ✓ |
| `4269→4326` | `(-121.5, 38.5)` ✓ | `(-121.5, 38.5)` ✓ |
| `CRS84→3857` | `(-13525318, 4650301)` ✓ | `(-13525318, 4650301)` ✓ |
| `CRS84→4326` | works ✓ | works ✓ |
| `3310→5070` | works ✓ | works ✓ |

**Rule**: Always use 4-argument `ST_Transform(geom, source_crs, dest_crs, true)` for ALL DuckDB spatial transforms. Never use the 2-argument `ST_Transform(ST_SetCRS(...), ...)` form.

### Why `always_xy=true`?

Without `always_xy=true`, DuckDB follows CRS axis order conventions. EPSG:4326's official axis order is `(lat, lon)`, so `ST_Transform` expects input in `(lat, lon)` order. Passing `(lon, lat)` coordinates without the flag causes the wrong axis to be transformed, producing infinity.

With `always_xy=true`:
- Input is always `(longitude, latitude)` regardless of CRS convention
- Output axis depends on CRS type: `(x, y)` for projected (3857, 3310, 5070), `(lon, lat)` for geographic (4326)
- No `ST_FlipCoordinates` needed ever — always produces PostGIS-compatible axis order

### CRS Names for DuckDB ST_Transform

| Source | CRS String | Notes |
|---|---|---|
| TIGER/Line shapefiles | `'EPSG:4269'` | NAD83, geographic |
| Overture GeoParquet | `'CRS84'` | OGC:CRS84, lon/lat geographic |
| GeoParquet native | `'EPSG:4326'` | When metadata says WGS 84 |
| Web Mercator | `'EPSG:3857'` | Projected, no axis ambiguity |
| CA Albers | `'EPSG:3310'` | Projected, California Teale Albers |
| Conus Albers | `'EPSG:5070'` | NLCD raster native CRS |
| US Albers | `'EPSG:6933'` | US National Atlas Equal Area |

## Column Naming Convention

When DuckDB staging VIEWs need both Web Mercator and geographic geometry:

| Column | SRID | SQL | Use |
|---|---|---|---|
| `geometry` | 3857 | `ST_Transform(geom, src, 'EPSG:3857', true)` | Map rendering, tiles |
| `wgs84_geometry` | 4326 | `ST_Transform(geom, src, 'EPSG:4326', true)` | Spatial joins, PostGIS |
| `local_geometry` | 3310 | `ST_Transform(geom, src, 'EPSG:3310', true)` | Area computations |

## Bridge Model Pattern (DuckDB FULL → PostGIS)

```sql
SELECT
  ST_SetCRS(geometry, 'EPSG:3857') AS geometry,
  ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry,
  ...
FROM duckdb.staging.source_view;
```

DuckDB's `ST_SetCRS` tags SRID metadata. When PostGIS accesses the table via FDW, the SRID metadata is **lost** (arrives as SRID=0). PostGIS models must re-tag with `ST_SetSRID`.

## PostGIS Downstream: Re-tagging After FDW

```sql
SELECT
  ST_SetSRID(geometry, 3857) AS geometry,
  ST_SetSRID(wgs84_geometry, 4326) AS wgs84_geometry,
  ...
FROM brewgis.staging.duckdb_bridge;
```

For a PostGIS VIEW wrapping a DuckDB FULL bridge:
```sql
SELECT
  geoid,
  ST_SetSRID(geometry, 3857) AS geometry,
  ST_SetSRID(wgs84_geometry, 4326) AS wgs84_geometry,
  ...
FROM brewgis.staging._bridge_table_raw;
```

## No FlipCoordinates Needed

With `always_xy=true`, both 3857 and 4326 outputs have PostGIS-correct axis order. Never use `ST_FlipCoordinates` on DuckDB output that used `always_xy=true`.

The only exception: if you use `ST_Transform(geom, 'EPSG:4326')` (2-arg) without always_xy, the EPSG:4326 output follows OGC axis order `(lat, lon)` which needs flipping for PostGIS. Avoid this — use the 4-arg form instead.

## Pre-existing CRS Detection

Check actual SRID of a PostGIS table:
```sql
SELECT ST_SRID(geometry) FROM table_name LIMIT 1;
```

List all geometry columns and their SRIDs:
```sql
SELECT f_table_name, srid, type FROM geometry_columns ORDER BY f_table_name;
```

## DuckDB Version

Checked in this session: `v1.5.4` (`Variegata`). The spatial extension behavior may differ between versions. The 4-arg ST_Transform with always_xy has been tested on 1.5.4 only.

## Testing ST_Transform in Python

```python
import duckdb
con = duckdb.connect("/path/to/cache.db")
con.execute("LOAD spatial")

# Test a transform
result = con.execute("""
    SELECT ST_Transform(
        ST_GeomFromText('POINT(-121.5 38.5)'),
        'EPSG:4269', 'EPSG:3857', true
    )
""").fetchone()
# result is WKB bytes — decode with struct
import struct
x, y = struct.unpack('<dd', result[0][5:21])
print(f"({x:.2f}, {y:.2f})")
```

## DuckDB ST_GeomFromText Quirks

DuckDB's `ST_GeomFromText` does NOT accept an SRID parameter:
- `ST_GeomFromText('POINT(...)', 4326)` → ❌ fails
- `ST_GeomFromText('POINT(...)')` → ✓ works (returns geometry with no CRS)

Use `ST_Transform`'s `source_crs` parameter to specify CRS, or use `ST_SetCRS` (DuckDB's equivalent of PostGIS's `ST_SetSRID`).

## SQLMesh DuckDB Gateway

Models using DuckDB:
```sql
MODEL (
  name duckdb.staging.my_model,
  kind VIEW,       -- DuckDB VIEW, no data materialized
  gateway duckdb,
  dialect duckdb
);
```

Bridge models that materialize DuckDB data for PostGIS:
```sql
MODEL (
  name brewgis.staging.my_model,
  kind FULL,       -- Materialized table in DuckDB
  gateway duckdb   -- DuckDB gateway
);
```

DuckDB FULL bridge models cannot use `CREATE INDEX` in `post_statements` — PostGIS GiST indexes must be created in a downstream PostGIS model's `pre_statements` or in a separate PostGIS FULL model.

## DuckDB ST_Read for Shapefiles

Read shapefiles from ZIP URLs:
```sql
SELECT column1, column2, geom
FROM ST_Read('zip://https://example.com/file.zip/file.shp')
WHERE filter_column = 'value';
```

The CRS of shapefiles read via `ST_Read` is EPSG:4269 (NAD83) for Census TIGER/Line data. Transform with `ST_Transform(geom, 'EPSG:4269', 'EPSG:3857', true)`.

## DuckDB ST_Transform vs PostGIS ST_Transform

PostGIS uses `ST_SetSRID(geom, srid)` + `ST_Transform(geom, dest_srid)` — a 2-form process with separate SRID tagging.

DuckDB uses `ST_SetCRS(geom, crs_string)` + `ST_Transform(geom, dest_crs_string)` — functionally similar but requires the 4-arg form for geographic→projected transforms.

The key difference: PostGIS's ST_Transform never produces NaN for valid coordinates, while DuckDB's 2-arg form silently produces NaN for geographic→projected transforms. Always use the 4-arg form in DuckDB.

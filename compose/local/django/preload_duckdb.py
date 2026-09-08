"""Pre-download DuckDB extensions into the image cache.

This runs at Docker build time.  At runtime, INSTALL is a no-op (~0.01s).
"""

import duckdb

con = duckdb.connect()
try:
    for ext in [
        "httpfs",
        "spatial",
        "postgres_scanner",
        "cache_httpfs",
        "zipfs",
        "raster",
    ]:
        if ext in ("cache_httpfs", "zipfs", "raster"):
            # FORCE: cache_httpfs artifacts pinned before ~2026-09 wedge on
            # s3:// parquet reads; always fetch the current community build.
            con.execute(f"FORCE INSTALL {ext} FROM community")
        else:
            con.execute(f"INSTALL {ext}")
        con.execute(f"LOAD {ext}")
    print("DuckDB extensions pre-loaded into image cache")
finally:
    con.close()

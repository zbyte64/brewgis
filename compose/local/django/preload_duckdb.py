"""Pre-download DuckDB extensions into the image cache.

This runs at Docker build time.  At runtime, INSTALL is a no-op (~0.01s).
"""

import duckdb

con = duckdb.connect()
try:
    for ext in ["httpfs", "spatial", "postgres_scanner"]:
        con.execute(f"INSTALL {ext}")
        con.execute(f"LOAD {ext}")
    print("DuckDB extensions pre-loaded into image cache")
finally:
    con.close()

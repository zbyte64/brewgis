#!/usr/bin/env python
"""Interactive DuckDB shell for the BrewGIS planning cache.

Connects to the DuckDB database used by the SQLMesh staging gateway
(`SQLMESH_DUCKDB_PATH`, defaulting to /app/planning/duckdb_cache.db) and
evaluates SQL statements interactively. Extensions (httpfs, spatial) are
loaded the same way the sqlmesh gateway does.

Usage:
    make duckdb            # inside the docker compose environment
    python scripts/duckdb_shell.py [path/to/cache.db]
"""

from __future__ import annotations

import os
import sys

import duckdb

DEFAULT_DB = os.environ.get("SQLMESH_DUCKDB_PATH", "/app/planning/duckdb_cache.db")

HELP = """\
Commands:
  .help         show this help
  .tables       list tables and views
  .schemas      list schemas
  .exit / .quit quit the shell
Anything else is evaluated as DuckDB SQL. Ctrl-D also quits.
"""


def render(cursor: duckdb.DuckDBPyConnection) -> str:
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        return "(0 rows)"
    widths = [len(c) for c in cols]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(str(value)))
    lines = ["  ".join(c.ljust(width) for c, width in zip(cols, widths, strict=False))]
    lines.append("  ".join("-" * width for width in widths))
    lines.extend(
        "  ".join(
            str(value).ljust(width) for value, width in zip(row, widths, strict=False)
        )
        for row in rows
    )
    return "\n".join(lines)


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    con = duckdb.connect(path)
    for ext in ("httpfs", "spatial"):
        con.execute(f"LOAD {ext}")
    print(f"Connected to {path} (DuckDB {duckdb.__version__})")
    print(HELP)
    while True:
        try:
            line = input("duckdb> ")
        except EOFError:
            print()
            break
        stmt = line.strip()
        if not stmt:
            continue
        command = stmt.lower()
        if command in (".exit", ".quit"):
            break
        if command == ".help":
            print(HELP)
            continue
        if command == ".tables":
            cursor = con.execute(
                "SELECT schema_name, table_name FROM duckdb_tables() "
                "UNION ALL SELECT schema_name, view_name FROM duckdb_views() "
                "ORDER BY 1, 2"
            )
        elif command == ".schemas":
            cursor = con.execute("SELECT schema_name FROM duckdb_schemas() ORDER BY 1")
        else:
            try:
                cursor = con.execute(stmt)
            except Exception as exc:
                print(f"Error: {exc}")
                continue
        try:
            out = render(cursor)
        except Exception:
            out = "(done)"  # DDL or other statements without a result set
        if out:
            print(out)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

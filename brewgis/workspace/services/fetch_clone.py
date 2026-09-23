# ruff: noqa: S608 — only quote-escaped identifiers are interpolated, never values
"""Copy of a SQLMesh fetch result into a workspace-owned Postgres table.

The Import Center's web fetches (Census ACS, LEHD LODES, OSM POI) run a SQLMesh
plan and then register a Django ``Layer`` over the result.  The fetch itself —
HTTP read, parsing, derivation, and the push into PostGIS — stays in SQLMesh
models: each fetch is a ``duckdb.*`` view that DuckDB reads (and caches) and a
gateway-duckdb bridge model that writes it into PostGIS as a ``brewgis.*`` table.
What Django adds is a plain copy in the workspace's own schema, because SQLMesh
rewrites an environment's schemas on every plan while a workspace schema is
never touched: an imported layer must keep the rows it was imported with.

The copy runs inside Postgres — ``CREATE TABLE <workspace>.<t> AS SELECT * FROM
<environment schema>.<model>`` — which is the fallback this fetch rework's plan
pre-decided for the case where the DuckDB push cannot carry the result.
Measured 2026-09-22, it cannot:

* a DuckDB file cannot be attached twice in one process ("Unique file handle
  conflict: ... is already attached by database ..."), and the process that ran
  a plan keeps it attached for its lifetime — ``Context.close()`` does not
  release it — so a DuckDB-catalogue fetch view is not readable by the copying
  connection;
* ``postgres_scanner`` transfers PostGIS geometry as SRID-less WKB in both
  directions: a clone of ``sacog__brewgis_prod.acs_block_group`` landed with
  ``ST_SRID(geometry) = 0`` even with ``ST_SetCRS`` applied inside the SELECT,
  and a typed PostGIS geometry column rejects SRID 0;
* the same round trip widens ``numeric`` to ``double precision``.

Copying where the source already sits avoids all three, and DuckDB still does
the fetching and the DuckDB-to-PostGIS push — that is what the bridge models are
for.
"""

from __future__ import annotations

import logging
from typing import Any

from brewgis.sqlmesh.macros.region_blueprints import region_profiles
from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)

# Environment whose promoted models the Import Center reads.
PROD_ENVIRONMENT = "brewgis_prod"

# Region whose models answer for a county no region profile claims.
DEFAULT_REGION = "sacog"


def model_source_ref(*, region: str, table: str) -> str:
    """Return the reference to a SQLMesh model materialized for the region.

    SQLMesh exposes an environment's models under the schema
    ``<model schema>__<environment>`` (``sacog__brewgis_prod``), so the
    reference resolves to whatever the latest plan for that environment built.
    """
    environment_schema = f"{region}__{PROD_ENVIRONMENT}"
    return f"{_quote(environment_schema)}.{_quote(table)}"


def clone_to_postgres(
    *,
    source_ref: str,
    dest_schema: str,
    dest_table: str,
) -> int:
    """Copy *source_ref* into ``dest_schema.dest_table``; return the row count.

    The destination is dropped first, so re-running a fetch replaces its own
    table instead of appending to it.
    """
    dest_ref = f"{_quote(dest_schema)}.{_quote(dest_table)}"
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_quote(dest_schema)}"))
        conn.execute(text(f"DROP TABLE IF EXISTS {dest_ref}"))
        conn.execute(text(f"CREATE TABLE {dest_ref} AS SELECT * FROM {source_ref}"))
        _restore_srid(
            conn=conn,
            source_ref=source_ref,
            dest_ref=dest_ref,
            dest_schema=dest_schema,
            dest_table=dest_table,
        )
        row = conn.execute(text(f"SELECT COUNT(*) FROM {dest_ref}")).scalar()
    row_count = int(row or 0)
    logger.info(
        "Cloned %d row(s) from %s into %s.%s",
        row_count,
        source_ref,
        dest_schema,
        dest_table,
    )
    return row_count


def _restore_srid(
    *,
    conn: Any,
    source_ref: str,
    dest_ref: str,
    dest_schema: str,
    dest_table: str,
) -> None:
    """Record EPSG:4326 on the copy when its geometry arrived without an SRID.

    A gateway-duckdb bridge cannot carry a geometry SRID through
    ``postgres_scanner`` — it transfers geometry as SRID-less WKB, so those
    tables store their geometry as SRID 0 (see ``models/osm/poi_bridge.sql``) and
    a copy of one inherits it. PostGIS operations and the tile servers read that
    SRID, so the copy records the CRS every fetch bridge produces.
    """
    columns = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table"
        ),
        {"schema": dest_schema, "table": dest_table},
    ).scalars()
    if "geometry" not in set(columns):
        return
    srid = conn.execute(
        text(
            "SELECT ST_SRID(geometry) FROM "
            f"{source_ref} WHERE geometry IS NOT NULL LIMIT 1"
        )
    ).scalar()
    if srid not in (0, None):
        return
    conn.execute(
        text(
            f"ALTER TABLE {dest_ref} ALTER COLUMN geometry "
            "TYPE geometry(Geometry, 4326) USING ST_SetSRID(geometry, 4326)"
        )
    )


def region_for_county(county_fips: str) -> str:
    """Return the region whose SQLMesh models serve *county_fips*.

    Region profiles are the single source of region boundaries
    (``region_blueprints.region_profiles``); a county no profile lists falls
    back to :data:`DEFAULT_REGION`.
    """
    for region, profile in region_profiles().items():
        counties = (c.strip() for c in str(profile.get("county_fips", "")).split(","))
        if county_fips in counties:
            return region
    return DEFAULT_REGION


def _quote(identifier: str) -> str:
    """Double-quote a SQL identifier, escaping any embedded quote."""
    return '"' + identifier.replace('"', '""') + '"'

"""SACOG v1 schema discovery — introspects the restored dump and reports table metadata."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

MANIFEST_PATH = (
    Path(settings.BASE_DIR)
    / "brewgis"
    / "workspace"
    / "services"
    / "sacog_schema_manifest.json"
)

# Tables whose schemas describe SACOG v1 parcel data
KEY_V1_TABLES = {
    "elk_grove_base_canvas": "Primary parcel table (52k rows, 86 cols) — pop, hh, du, emp, bldg_sqft, acres",
    "footprint_flatbuiltform": "FlatBuiltForm catalog (667 rows) — built form density/intensity profiles",
    "parcel_tag": "Constraint overlay (661k rows) — flood, habitat, endangered species, conservation",
    "elk_grove_existing_land_use_parcels": "Existing land use parcels (52k rows)",
    "elk_grove_base_agriculture_canvas": "Agriculture canvas (52k rows) — crop yield, water, market value",
    "sac_cnty_census_rates": "Census rates (913 rows) — household income, tenure by block group",
    "sac_cnty_census_blockgroups": "Census block group geometry (912 rows)",
    "sac_cnty_census_blocks": "Census blocks (19,937 rows)",
    "sac_cnty_census_tracts": "Census tracts (318 rows)",
    "sac_cnty_climate_zones": "Climate zones (726 rows) — evapotranspiration, forecasting, Title 24",
    "sac_cnty_cpad_holdings": "CPAD conservation holdings (1,395 rows)",
    "elk_grove_base_transit_stops": "Base transit stops (5,158 rows)",
    "elk_grove_future_transit_stops": "Future transit stops (5,158 rows)",
    "elk_grove_vmt_base_trip_lengths": "VMT base trip lengths (1,502 rows)",
    "elk_grove_vmt_future_trip_lengths": "VMT future trip lengths (1,502 rows)",
    "sac_cnty_base_transit_stops": "Base transit stops county-wide (5,158 rows)",
    "sac_cnty_future_transit_stops": "Future transit stops county-wide (5,158 rows)",
}


def discover_schema() -> dict:
    """Discover all restored v1 tables and columns.

    Returns the manifest dict and writes it to MANIFEST_PATH as JSON.
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast', 'topology')
              AND schema_name NOT LIKE 'pg_%'
            ORDER BY schema_name
        """)
        schemas = [r[0] for r in cursor.fetchall()]

    manifest: dict[str, dict] = {}

    for schema in schemas:
        with connection.cursor() as cursor:
            manifest[schema] = _discover_schema_tables(cursor, schema)

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    logger.info(
        "Schema manifest written to %s (%d schemas)", MANIFEST_PATH, len(manifest)
    )
    return manifest


def _discover_schema_tables(cursor, schema: str) -> dict:
    """Introspect all tables in *schema*."""
    cursor.execute(
        "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name",
        [schema],
    )
    tables = cursor.fetchall()

    result: dict[str, dict] = {}
    for table_name, table_type in tables:
        info = _inspect_table(cursor, schema, table_name)
        info["type"] = table_type
        result[table_name] = info
    return result


def _inspect_table(cursor, schema: str, table_name: str) -> dict:
    """Return column metadata and row count for a table."""
    row_count = _table_row_count(cursor, schema, table_name)

    cursor.execute(
        """SELECT column_name, data_type, is_nullable, character_maximum_length
           FROM information_schema.columns
           WHERE table_schema = %s AND table_name = %s
           ORDER BY ordinal_position""",
        [schema, table_name],
    )
    columns = [
        {
            "name": r[0],
            "type": r[1],
            "nullable": r[2] == "YES",
            "max_length": r[3],
        }
        for r in cursor.fetchall()
    ]

    return {
        "row_count": row_count,
        "columns": columns,
    }


def _table_row_count(cursor, schema: str, table_name: str) -> int:
    try:
        cursor.execute(
            'SELECT count(*) FROM "%s"."%s"'
            % (schema.replace('"', '""'), table_name.replace('"', '""'))
        )
        return cursor.fetchone()[0]
    except Exception:
        return -1


def load_manifest() -> dict:
    """Load the cached schema manifest from disk, or discover fresh if missing."""
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            return dict(json.load(f))
    return discover_schema()


def print_summary(manifest: dict | None = None) -> None:
    """Print a human-readable summary of the schema."""
    if manifest is None:
        manifest = load_manifest()
    for schema, tables in manifest.items():
        print(f"\n=== Schema: {schema} ({len(tables)} tables) ===")
        for table_name, info in sorted(tables.items()):
            cols = info.get("columns", [])
            col_preview = ", ".join(c["name"] for c in cols[:10])
            if len(cols) > 10:
                col_preview += f" ... +{len(cols) - 10} more"
            extra = ""
            if table_name in KEY_V1_TABLES:
                extra = f"  ← {KEY_V1_TABLES[table_name]}"
            print(f"  {table_name}: {info['row_count']} rows, {len(cols)} cols{extra}")
            print(f"    Cols: {col_preview}")

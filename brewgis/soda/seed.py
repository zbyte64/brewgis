"""Seed Soda contract target tables with representative test data.

Each function creates the target table (if absent) and inserts minimal seed rows
that satisfy the contract's checks (non-null identifiers, non-negative numerics,
row_count > 0).  Idempotent — skips if the table already exists.

Geometry columns use real ``GEOMETRY(GEOMETRY, 4326)`` PostGIS types populated
via ``ST_GeomFromText`` so that SRID and geometry-type checks work against
seed data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import connection

if TYPE_CHECKING:
    from collections.abc import Iterable


def seed_all() -> None:
    """Create and populate every table that Soda contracts expect to exist."""
    seeders: dict[str, tuple[str, ...]] = {
        "base_canvas": _base_canvas(),
        "census_acs": _census_acs(),
        "lehd_lodes": _lehd_lodes(),
        "poi": _poi(),
        "nlcd": _nlcd(),
        "synthetic_parcels": _synthetic_parcels(),
        "spatial_allocation": _spatial_allocation(),
        "column_stitching": _column_stitching(),
        "census.acs_block_group": _acs_block_group(),
        "lehd.wac_block": _wac_block(),
    }
    for table, seeder in seeders.items():
        ddl, *rest = seeder
        if len(rest) == 2:
            dml_template, rows = rest
        else:
            dml_template, rows = None, rest[0]
        _ensure_table(table, ddl, rows, dml_template)


# ── Concrete table definitions ──────────────────────────────────────────


def _base_canvas() -> tuple[str, str, list[tuple[str, ...]]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS public.base_canvas (
            geography_id VARCHAR(32) NOT NULL,
            geometry GEOMETRY(GEOMETRY, 4326) NOT NULL,
            pop DOUBLE PRECISION NOT NULL,
            du DOUBLE PRECISION NOT NULL,
            area_parcel DOUBLE PRECISION NOT NULL,
            hh DOUBLE PRECISION NOT NULL,
            residential_irrigated_area DOUBLE PRECISION NOT NULL,
            commercial_irrigated_area DOUBLE PRECISION NOT NULL,
            median_income DOUBLE PRECISION NOT NULL,
            rent_burden_pct DOUBLE PRECISION NOT NULL,
            pct_minority DOUBLE PRECISION NOT NULL,
            pct_college_educated DOUBLE PRECISION NOT NULL,
            cost_burden_pct DOUBLE PRECISION NOT NULL,
            intersection_density DOUBLE PRECISION NOT NULL
        )
    """
    dml_template = (
        'INSERT INTO {schema}."{table}" '
        "VALUES (%s, ST_GeomFromText(%s, 4326), %s, %s, %s, %s, "
        "%s, %s, %s, %s, %s, %s, %s, %s)"
    )
    rows = [
        (
            "GEO001",
            "POINT(-119.5 36.5)",
            5000.0,  # pop
            1800.0,  # du
            850.0,  # area_parcel
            1700.0,  # hh
            200.0,  # residential_irrigated_area
            50.0,  # commercial_irrigated_area
            65000.0,  # median_income
            30.0,  # rent_burden_pct
            40.0,  # pct_minority
            35.0,  # pct_college_educated
            25.0,  # cost_burden_pct
            12.0,  # intersection_density
        ),
    ]
    return ddl, dml_template, rows


def _census_acs() -> tuple[str, list[tuple]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS public.census_acs (
            year INTEGER NOT NULL,
            state VARCHAR(2) NOT NULL,
            county VARCHAR(3) NOT NULL,
            tract VARCHAR(11) NOT NULL,
            block_group VARCHAR(1) NOT NULL,
            b01001_001_e DOUBLE PRECISION NOT NULL,
            b25003_001_e DOUBLE PRECISION NOT NULL
        )
    """
    rows = [
        (2022, "06", "019", "000100", "1", 5000.0, 1800.0),
    ]
    return ddl, rows


def _lehd_lodes() -> tuple[str, list[tuple]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS public.lehd_lodes (
            w_geocode VARCHAR(15) NOT NULL,
            c000 INTEGER NOT NULL,
            year INTEGER NOT NULL
        )
    """
    rows = [
        ("060190001001000", 250, 2022),
    ]
    return ddl, rows


def _poi() -> tuple[str, str, list[tuple[str, ...]]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS public.poi (
            osm_id BIGINT NOT NULL,
            name VARCHAR(256) NOT NULL,
            category VARCHAR(64) NOT NULL,
            geometry GEOMETRY(GEOMETRY, 4326) NOT NULL,
            lat DOUBLE PRECISION NOT NULL,
            lon DOUBLE PRECISION NOT NULL
        )
    """
    dml_template = (
        'INSERT INTO {schema}."{table}" '
        "VALUES (%s, %s, %s, ST_GeomFromText(%s, 4326), %s, %s)"
    )
    rows = [
        (123456, "Test Park", "park", "POINT(-119.5 36.5)", 36.5, -119.5),
    ]
    return ddl, dml_template, rows


def _nlcd() -> tuple[str, str, list[tuple[str, ...]]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS public.nlcd (
            geoid VARCHAR(15) NOT NULL,
            impervious_pct DOUBLE PRECISION NOT NULL,
            canopy_pct DOUBLE PRECISION NOT NULL,
            land_cover_class VARCHAR(64) NOT NULL,
            geometry GEOMETRY(GEOMETRY, 4326) NOT NULL
        )
    """
    dml_template = (
        'INSERT INTO {schema}."{table}" '
        "VALUES (%s, %s, %s, %s, ST_GeomFromText(%s, 4326))"
    )
    rows = [
        (
            "060190001001000",
            35.0,
            15.0,
            "Developed, Medium Intensity",
            "POINT(-119.5 36.5)",
        ),
    ]
    return ddl, dml_template, rows


def _synthetic_parcels() -> tuple[str, str, list[tuple[str, ...]]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS public.synthetic_parcels (
            parcel_id VARCHAR(32) NOT NULL,
            geometry GEOMETRY(GEOMETRY, 4326) NOT NULL,
            pop DOUBLE PRECISION NOT NULL,
            du DOUBLE PRECISION NOT NULL,
            area_parcel DOUBLE PRECISION NOT NULL,
            hh DOUBLE PRECISION NOT NULL,
            median_income DOUBLE PRECISION NOT NULL,
            rent_burden_pct DOUBLE PRECISION NOT NULL,
            pct_minority DOUBLE PRECISION NOT NULL,
            pct_college_educated DOUBLE PRECISION NOT NULL,
            cost_burden_pct DOUBLE PRECISION NOT NULL
        )
    """
    dml_template = (
        'INSERT INTO {schema}."{table}" '
        "VALUES (%s, ST_GeomFromText(%s, 4326), %s, %s, %s, %s, "
        "%s, %s, %s, %s, %s)"
    )
    rows = [
        (
            "PARCEL001",
            "POINT(-119.5 36.5)",
            2.5,  # pop
            1.0,  # du
            0.25,  # area_parcel (acres)
            1.0,  # hh
            65000.0,  # median_income
            30.0,  # rent_burden_pct
            40.0,  # pct_minority
            35.0,  # pct_college_educated
            25.0,  # cost_burden_pct
        ),
    ]
    return ddl, dml_template, rows


def _spatial_allocation() -> tuple[str, list[tuple]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS public.spatial_allocation (
            target_geoid VARCHAR(15) NOT NULL,
            source_geoid VARCHAR(15) NOT NULL,
            allocated_population DOUBLE PRECISION NOT NULL,
            allocated_employment DOUBLE PRECISION NOT NULL,
            allocation_weight DOUBLE PRECISION NOT NULL
        )
    """
    rows = [
        ("060190001001000", "060190001001000", 2500.0, 800.0, 1.0),
    ]
    return ddl, rows


def _column_stitching() -> tuple[str, list[tuple]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS public.column_stitching (
            parcel_id VARCHAR(32) NOT NULL,
            imputed_population DOUBLE PRECISION NOT NULL,
            imputed_households DOUBLE PRECISION NOT NULL,
            imputed_employment DOUBLE PRECISION NOT NULL,
            imputed_du DOUBLE PRECISION NOT NULL
        )
    """
    rows = [
        ("PARCEL001", 2.5, 1.0, 0.0, 1.0),
    ]
    return ddl, rows


def _acs_block_group() -> tuple[str, str, list[tuple[str, ...]]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS census.acs_block_group (
            geoid VARCHAR(15) NOT NULL,
            geometry GEOMETRY(GEOMETRY, 4326) NOT NULL,
            pop DOUBLE PRECISION NOT NULL,
            hh DOUBLE PRECISION NOT NULL,
            du DOUBLE PRECISION NOT NULL,
            median_income DOUBLE PRECISION NOT NULL
        )
    """
    dml_template = (
        'INSERT INTO {schema}."{table}" '
        "VALUES (%s, ST_GeomFromText(%s, 4326), %s, %s, %s, %s)"
    )
    rows = [
        (
            "060190001001001",
            "POINT(-119.5 36.5)",
            2500.0,  # pop
            950.0,  # hh
            1050.0,  # du
            55000.0,  # median_income
        ),
    ]
    return ddl, dml_template, rows


def _wac_block() -> tuple[str, str, list[tuple[str, ...]]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS lehd.wac_block (
            geoid VARCHAR(15) NOT NULL,
            geometry GEOMETRY(GEOMETRY, 4326) NOT NULL,
            emp DOUBLE PRECISION NOT NULL,
            emp_ret DOUBLE PRECISION NOT NULL
        )
    """
    dml_template = (
        'INSERT INTO {schema}."{table}" VALUES (%s, ST_GeomFromText(%s, 4326), %s, %s)'
    )
    rows = [
        (
            "060190001001001",
            "POINT(-119.5 36.5)",
            1200.0,  # emp
            300.0,  # emp_ret
        ),
    ]
    return ddl, dml_template, rows


# ── Helpers ─────────────────────────────────────────────────────────────


def _ensure_table(
    table: str,
    ddl: str,
    rows: Iterable[tuple],
    dml_template: str | None = None,
) -> None:
    """Create *table* if missing and insert *rows*.

    *table* may be ``schema.table`` or just ``table`` (defaults to ``public``).

    When *dml_template* is provided, the table is always dropped and recreated
    so that schema changes (e.g. ``TEXT`` → ``GEOMETRY``) take effect on
    existing seed databases.  The template uses ``{schema}`` and ``{table}``
    placeholders substituted at execution time to support PostGIS function
    calls (``ST_GeomFromText``) for geometry columns.
    """
    parts = table.split(".", 1)
    if len(parts) == 2:
        schema, tbl = parts
    else:
        schema, tbl = "public", parts[0]

    with connection.cursor() as cursor:
        if dml_template:
            cursor.execute(
                f'DROP TABLE IF EXISTS {connection.ops.quote_name(schema)}."{tbl}" CASCADE'
            )
        else:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s)",
                [schema, tbl],
            )
            if cursor.fetchone()[0]:
                return
        if schema != "public":
            cursor.execute(
                f"CREATE SCHEMA IF NOT EXISTS {connection.ops.quote_name(schema)}"
            )
        cursor.execute(ddl)
        if rows:
            if dml_template:
                stmt = dml_template.format(
                    schema=connection.ops.quote_name(schema), table=tbl
                )
            else:
                placeholders = ", ".join(["%s"] * len(next(iter(rows))))
                stmt = 'INSERT INTO {}."{}" VALUES ({})'.format(  # noqa: S608
                    connection.ops.quote_name(schema),
                    tbl,
                    placeholders,
                )
            cursor.executemany(stmt, rows)

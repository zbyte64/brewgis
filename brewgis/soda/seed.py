"""Seed Soda contract target tables with representative test data.

Each function creates the target table (if absent) and inserts minimal seed rows
that satisfy the contract's checks (non-null identifiers, non-negative numerics,
row_count > 0).  Idempotent — skips if the table already exists.

Geometry columns use a simple ``POINT(0 0)`` WKT text representation; the Soda
contracts only check for NULL, not geometry validity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import connection

if TYPE_CHECKING:
    from collections.abc import Iterable


def seed_all() -> None:
    """Create and populate every table that Soda contracts expect to exist."""
    seeders: dict[str, tuple[str, list[tuple]]] = {
        "census_acs": _census_acs(),
        "lehd_lodes": _lehd_lodes(),
        "poi": _poi(),
        "nlcd": _nlcd(),
        "synthetic_parcels": _synthetic_parcels(),
        "spatial_allocation": _spatial_allocation(),
        "column_stitching": _column_stitching(),
    }
    for table, (ddl, rows) in seeders.items():
        _ensure_table(table, ddl, rows)


# ── Concrete table definitions ──────────────────────────────────────────


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


def _poi() -> tuple[str, list[tuple]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS public.poi (
            osm_id BIGINT NOT NULL,
            name VARCHAR(256) NOT NULL,
            category VARCHAR(64) NOT NULL,
            geometry TEXT NOT NULL,
            lat DOUBLE PRECISION NOT NULL,
            lon DOUBLE PRECISION NOT NULL
        )
    """
    rows = [
        (123456, "Test Park", "park", "POINT(-119.5 36.5)", 36.5, -119.5),
    ]
    return ddl, rows


def _nlcd() -> tuple[str, list[tuple]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS public.nlcd (
            geoid VARCHAR(15) NOT NULL,
            impervious_pct DOUBLE PRECISION NOT NULL,
            canopy_pct DOUBLE PRECISION NOT NULL,
            land_cover_class VARCHAR(64) NOT NULL,
            geometry TEXT NOT NULL
        )
    """
    rows = [
        ("060190001001000", 35.0, 15.0, "Developed, Medium Intensity", "POINT(-119.5 36.5)"),
    ]
    return ddl, rows


def _synthetic_parcels() -> tuple[str, list[tuple]]:
    ddl = """
        CREATE TABLE IF NOT EXISTS public.synthetic_parcels (
            parcel_id VARCHAR(32) NOT NULL,
            geometry TEXT NOT NULL,
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
    return ddl, rows


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


# ── Helpers ─────────────────────────────────────────────────────────────


def _ensure_table(table: str, ddl: str, rows: Iterable[tuple]) -> None:
    """Create *table* if missing and insert *rows*."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s)",
            [table],
        )
        if cursor.fetchone()[0]:
            return

        cursor.execute(ddl)
        if rows:
            placeholders = ", ".join(["%s"] * len(next(iter(rows))))
            # table is a trusted contract name, not user input
            stmt = 'INSERT INTO public."{}" VALUES ({})'.format(  # noqa: S608 — table is a trusted contract name, not user input
                table, placeholders,
            )
            cursor.executemany(stmt, rows)

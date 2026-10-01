# ruff: noqa: PLC0415, S608 — the model module resolves its blueprints from the
# database while SQLMesh imports it, and the probe's schema and table names are
# literals here, not bind parameters.
"""Tests for the built-form fill's key rule, run against PostGIS.

The fill exists to resolve the base-canvas ETL's uniform ``mixed_use``
placeholder. It is *not* a licence to overwrite a canvas that names real built
forms: a key that resolves to one of the workspace's Building Types is the
source's own assertion and is kept, raw spelling and all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

import pytest
from django.db import connection

from brewgis.workspace.services.base_canvas_schema import EMPLOYMENT_SECTORS
from brewgis.workspace.services.built_form_keys import PLACEHOLDER_BUILT_FORM_KEY
from tests.factories import BuildingTypeFactory
from tests.factories import WorkspaceFactory

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlmesh.core.macros import MacroEvaluator

_SCHEMA = "fill_probe"

# The source's columns, in the order the blueprint reads them. The sector
# columns are what the sector *preference* ranks candidates by, so the source
# carries one per sector the canvas vocabulary knows.
_COLUMNS: tuple[str, ...] = (
    "parcel_id",
    "land_development_category",
    "built_form_key",
    "du",
    "pop",
    "hh",
    "emp",
    "area_gross",
    "area_parcel",
    *(f"emp_{sector}" for sector in EMPLOYMENT_SECTORS),
)

# One workspace's Building Type library: the display names the paint surfaces
# write, one entry naming no category (the library's own Mixed Use, whose
# category no parcel vocabulary can express) and densities far enough apart that
# the closest match is never ambiguous.
_LIBRARY: tuple[tuple[str, str, float, float], ...] = (
    ("Single-Family Detached - Large Lot", "urban", 2.0, 0.0),
    ("Courtyard Apartment", "urban", 40.0, 0.0),
    ("Neighborhood Retail", "urban", 0.0, 30.0),
    ("Office - Mid/High Rise", "urban", 30.0, 60.0),
    ("Mixed Use", "", 25.0, 25.0),
)

# parcel id → (built_form_key, du, emp). Every parcel is 10 acres in the urban
# category, so the closest urban match is decided by density alone: 4 du/acre
# is Single-Family Detached - Large Lot (2 du/acre), 30 emp/acre is
# Neighborhood Retail (30) and 60 emp/acre is Office - Mid/High Rise (60).
_PARCELS: tuple[tuple[str, str | None, float | None, float], ...] = (
    # The ETL's placeholder: no built form was carried, so the match resolves it.
    ("p_etl_placeholder", PLACEHOLDER_BUILT_FORM_KEY, 40.0, 0.0),
    # A display name, an ETL slug and the library's own Mixed Use: the same
    # assertion in the three spellings a canvas may carry it in. Each parcel's
    # density points at a *different* entry than its key names, which is what
    # makes these observational rather than tautological.
    ("p_display_name", "Courtyard Apartment", 40.0, 0.0),
    ("p_etl_slug", "bt__neighborhood_retail", 0.0, 300.0),
    ("p_mixed_use_name", "Mixed Use", 40.0, 0.0),
    # Nothing asserted: the placeholder's neighbours in the ETL's vocabulary.
    ("p_blank", "   ", 40.0, 0.0),
    ("p_null", None, 40.0, 0.0),
    # A slug no entry answers to is not an assertion either.
    ("p_unknown_slug", "bt__unobtainium", 40.0, 0.0),
    # No key and no dwelling units: the match supplies the key and the NULL du.
    ("p_emp_driven", None, None, 600.0),
)

# parcel id → the row the fill must produce: its built_form_key, and the du it
# fills (or keeps) and the emp it must leave alone.
_EXPECTED: dict[str, tuple[str, float, float]] = {
    "p_etl_placeholder": ("Single-Family Detached - Large Lot", 40.0, 0.0),
    "p_display_name": ("Courtyard Apartment", 40.0, 0.0),
    "p_etl_slug": ("bt__neighborhood_retail", 0.0, 300.0),
    "p_mixed_use_name": ("Mixed Use", 40.0, 0.0),
    "p_blank": ("Single-Family Detached - Large Lot", 40.0, 0.0),
    "p_null": ("Single-Family Detached - Large Lot", 40.0, 0.0),
    "p_unknown_slug": ("Single-Family Detached - Large Lot", 40.0, 0.0),
    "p_emp_driven": ("Office - Mid/High Rise", 300.0, 600.0),
}


@dataclass
class _Evaluator:
    """The blueprint variables ``execute`` reads — and nothing else of SQLMesh."""

    variables: dict[str, Any]

    def blueprint_var(self, name: str, default: Any = None) -> Any:
        return self.variables.get(name, default)


@pytest.fixture
def probe(db) -> Iterator[dict[str, Any]]:
    """A base-canvas-shaped source and one workspace's Building Type library.

    The fill's SQL is built from the workspace's blueprint, which the model
    resolves while SQLMesh loads the project — so the shape that matters here is
    what that blueprint carries: the source's name, its column list, and the
    workspace whose Building Types the match joins against. A second workspace
    holds a library entry that would win every match, so a fill that read past
    its own workspace's rows would show it.
    """
    workspace = WorkspaceFactory()
    for name, category, du_per_acre, emp_per_acre in _LIBRARY:
        BuildingTypeFactory(
            workspace=workspace,
            name=name,
            land_development_category=category,
            du_per_acre=du_per_acre,
            emp_per_acre=emp_per_acre,
        )
    BuildingTypeFactory(
        name="Another Workspace's Exact Match",
        land_development_category="urban",
        du_per_acre=4.0,
        emp_per_acre=60.0,
    )

    sector_columns = ", ".join(
        f"emp_{sector} DOUBLE PRECISION" for sector in EMPLOYMENT_SECTORS
    )
    # parcel_id, category, key, du, pop, hh, emp, area_gross, area_parcel, then
    # one employment column per sector — all zero, no parcel here has jobs.
    row = (
        "(%s, 'urban', %s, %s, 0, 0, %s, 10, 10" + ", 0" * len(EMPLOYMENT_SECTORS) + ")"
    )
    with connection.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
        cursor.execute(f"CREATE SCHEMA {_SCHEMA}")
        cursor.execute(f"""
            CREATE TABLE {_SCHEMA}.parcels (
                parcel_id TEXT PRIMARY KEY,
                land_development_category TEXT,
                built_form_key TEXT,
                du DOUBLE PRECISION,
                pop DOUBLE PRECISION,
                hh DOUBLE PRECISION,
                emp DOUBLE PRECISION,
                area_gross DOUBLE PRECISION,
                area_parcel DOUBLE PRECISION,
                {sector_columns}
            )
        """)
        cursor.execute(
            f"INSERT INTO {_SCHEMA}.parcels"
            f" ({', '.join(_COLUMNS)}) VALUES {', '.join(row for _ in _PARCELS)}",
            [value for pid, key, du, emp in _PARCELS for value in (pid, key, du, emp)],
        )
    try:
        yield {
            "source_ref": f"{_SCHEMA}.parcels",
            "workspace_id": workspace.pk,
            "all_columns": list(_COLUMNS),
        }
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")


def _filled(blueprint: dict[str, Any]) -> dict[str, tuple[str, float, float]]:
    """Run the fill model's SQL over the probe and return parcel id → row."""
    # Imported here, not at module scope: the module resolves its blueprint
    # profiles from the database while SQLMesh imports it.
    from brewgis.sqlmesh.models.base_canvas import built_form_fill

    sql = built_form_fill.execute(cast("MacroEvaluator", _Evaluator(blueprint)))

    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT parcel_id, built_form_key, du, emp FROM ({sql}) AS filled"
            " ORDER BY parcel_id"
        )
        return {row[0]: (row[1], row[2], row[3]) for row in cursor.fetchall()}


@pytest.mark.integration
class TestKeyRule:
    """Which source keys the fill replaces, and which it leaves alone."""

    def test_keeps_the_keys_the_library_answers_to(self, probe) -> None:
        """A display name, an ETL slug and the library's own Mixed Use survive.

        Each parcel's density matches a different entry than the one its key
        names, so the fill that overwrote keys would move all three.
        """
        filled = _filled(probe)

        assert filled["p_display_name"][0] == "Courtyard Apartment"
        assert filled["p_etl_slug"][0] == "bt__neighborhood_retail"
        assert filled["p_mixed_use_name"][0] == "Mixed Use"

    def test_replaces_the_keys_that_name_no_building_type(self, probe) -> None:
        """The placeholder, a blank, a NULL and an unknown slug all move.

        ``mixed_use`` is the case the feature exists for — and the reason the
        placeholder is compared by its raw spelling: normalized it resolves to
        the library's ``Mixed Use``, which the parcel above keeps.
        """
        filled = _filled(probe)

        assert filled["p_etl_placeholder"][0] == "Single-Family Detached - Large Lot"
        assert filled["p_blank"][0] == "Single-Family Detached - Large Lot"
        assert filled["p_null"][0] == "Single-Family Detached - Large Lot"
        assert filled["p_unknown_slug"][0] == "Single-Family Detached - Large Lot"

    def test_leaves_the_parcel_columns_the_source_already_measured(self, probe) -> None:
        """The whole outcome, column by column: the match fills a NULL ``du``
        and supplies the key, while a measured 0 or 600 stays what the source
        said it was."""
        assert _filled(probe) == _EXPECTED

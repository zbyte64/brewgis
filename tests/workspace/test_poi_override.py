# ruff: noqa: ANN201
"""Consistency checks for the POI built-form override's two seed inputs.

``brewgis.seeds.poi_built_form_map`` maps an Overpass POI category to the built
form a parcel containing a point of that category takes; the override then reads
that built form out of ``brewgis.seeds.default_built_forms`` (the seeded
``DEFAULT_BUILDING_TYPES`` library) and sets the parcel's dwelling units and
employment from it.

The three files involved — the seed CSV, the library and the Overpass taxonomy —
are edited independently, and each drift between them fails *silently*:

* a ``built_form_key`` the library does not define leaves that join empty, so the
  override returns null ``du``/``emp`` for the category and the imputation tier
  below fills them with a county average — a parcel that looks overridden but is
  not;
* a ``poi_category`` the taxonomy does not fetch can never match a fetched point;
* a taxonomy category with no map row is quietly never overridden;
* a mapped built form that houses people contradicts the override's zeroed DU
  subtypes (its ``assert_du_subtype_sum_equals_du`` audit);
* a mapped built form that employs people with no ``jobs_by_sector`` mix splits
  its jobs across no sector.

These are properties of the checked-in files, so they are asserted here rather
than in the SQLMesh model test, which stubs both seeds to keep its assertions
independent of the library's numbers.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from brewgis.sqlmesh.macros.overpass_fetch import POI_CATEGORIES
from brewgis.sqlmesh.models.seeds.default_built_forms import normalize_shares
from brewgis.workspace.built_forms.default_library import DEFAULT_BUILDING_TYPES
from brewgis.workspace.services.base_canvas_schema import EMPLOYMENT_SECTORS

_MAP_CSV = (
    Path(__file__).resolve().parents[2]
    / "brewgis"
    / "sqlmesh"
    / "seeds"
    / "poi_built_form_map.csv"
)


def _map_rows() -> list[dict[str, str]]:
    """Read the seed map's rows (every field is text, as the CSV carries it)."""
    with _MAP_CSV.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _positive(mix: dict[str, Any] | None) -> dict[str, Any]:
    """The declared sectors of a share mix: a zero share states nothing."""
    return {sector: value for sector, value in (mix or {}).items() if value}


def _library_by_name() -> dict[str, dict[str, Any]]:
    return {entry["name"]: entry for entry in DEFAULT_BUILDING_TYPES}


def test_map_covers_exactly_the_fetched_taxonomy():
    """Every fetched category is mapped, and no map row names an unfetched one."""
    assert {row["poi_category"] for row in _map_rows()} == set(POI_CATEGORIES)


def test_priorities_are_unique():
    """A tie would make the override's DISTINCT ON pick a category at random."""
    priorities = [row["priority"] for row in _map_rows()]
    assert len(set(priorities)) == len(priorities)


def test_every_mapped_built_form_is_in_the_seeded_library():
    """A missing key would null the parcel's densities instead of overriding them."""
    library = _library_by_name()
    missing = sorted({row["built_form_key"] for row in _map_rows()} - set(library))
    assert not missing, (
        f"poi_built_form_map names built forms the library does not define: {missing}"
    )


def test_mapped_built_forms_house_nobody():
    """The override zeroes DU subtypes, so a mapped form may not imply dwellings."""
    library = _library_by_name()
    residential = sorted(
        {
            row["built_form_key"]
            for row in _map_rows()
            if library[row["built_form_key"]]["du_per_acre"]
        }
    )
    assert not residential, (
        f"the override zeroes DU subtypes, so these may not be mapped: {residential}"
    )


def test_mapped_built_forms_that_employ_declare_a_sector():
    """Jobs with no share mix would land on no sector column at all."""
    library = _library_by_name()
    sectorless = sorted(
        {
            row["built_form_key"]
            for row in _map_rows()
            if library[row["built_form_key"]]["emp_per_acre"]
            and not _positive(library[row["built_form_key"]]["jobs_by_sector"])
        }
    )
    assert not sectorless, (
        f"these are mapped but declare no sector for their jobs: {sectorless}"
    )


def test_mapped_built_forms_use_known_sectors():
    """A sector outside the vocabulary has no emp_<sector> column to land in."""
    library = _library_by_name()
    unknown = sorted(
        {
            sector
            for row in _map_rows()
            for sector in _positive(library[row["built_form_key"]]["jobs_by_sector"])
            if sector not in EMPLOYMENT_SECTORS
        }
    )
    assert not unknown, f"these sectors have no base canvas column: {unknown}"


def test_library_share_mixes_normalize_to_full_coverage():
    """``default_built_forms`` normalizes shares to 100, so a form's sectors cover its jobs.

    The override reads each sub-sector as ``emp_total * share / 100``, and the
    reconciliation audits expect the sub-sectors to add back up to the form's
    ``emp``; both need the normalized shares to sum to exactly 100.
    """
    empty: list[str] = []
    wrong: dict[str, float] = {}
    for entry in DEFAULT_BUILDING_TYPES:
        shares = normalize_shares(entry["jobs_by_sector"])
        if not _positive(entry["jobs_by_sector"]):
            if shares:
                empty.append(entry["name"])
            continue
        total = sum(shares.values())
        assert set(shares) == set(_positive(entry["jobs_by_sector"])), entry["name"]
        if total != pytest.approx(100.0):
            wrong[entry["name"]] = total
    assert not empty, f"these declare no sector yet normalize to one: {empty}"
    assert not wrong, f"these share mixes do not normalize to 100: {wrong}"

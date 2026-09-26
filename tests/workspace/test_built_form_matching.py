# ruff: noqa: ARG002 — the ``db`` fixture is an argument, not a reference
"""Tests for the built-form matching rules (``built_forms.matching``).

One constraint (the parcel's land development category) and one preference (the
parcel's dominant employment sector) sit on top of the density bases. Each is
implemented twice — Python for the paint surfaces, SQL for the base-canvas fill
model — so each pair is tested for agreement, not just for its own behavior.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection

from brewgis.workspace.built_forms.matching import category_requirement_sql
from brewgis.workspace.built_forms.matching import declared_sectors
from brewgis.workspace.built_forms.matching import dominant_employment_sector
from brewgis.workspace.built_forms.matching import prefer_same_sector
from brewgis.workspace.built_forms.matching import require_same_category
from brewgis.workspace.built_forms.models import BuildingType


def _building_type(**fields: Any) -> BuildingType:
    """An unsaved BuildingType — these rules read fields, they never query."""
    return BuildingType(**fields)


@pytest.mark.models
class TestDominantEmploymentSector:
    """The parcel-side half of the sector rule."""

    def test_largest_sector_wins(self) -> None:
        row = {"emp_military": 4.0, "emp_office_services": 1.0}
        assert dominant_employment_sector(row) == "military"

    def test_tie_goes_to_the_alphabetically_first_sector(self) -> None:
        """The tie-break the SQL twin uses too, so both surfaces agree."""
        row = {"emp_military": 3.0, "emp_office_services": 3.0}
        assert dominant_employment_sector(row) == "military"

    def test_no_jobs_is_no_sector(self) -> None:
        assert dominant_employment_sector({}) is None
        assert dominant_employment_sector({"emp_military": 0.0}) is None
        assert dominant_employment_sector({"emp_military": None}) is None

    def test_aggregate_columns_are_ignored(self) -> None:
        """``emp`` and its group totals are sums of the sectors, never sectors."""
        assert dominant_employment_sector({"emp": 10.0, "emp_ret": 5.0}) is None


@pytest.mark.models
class TestPreferences:
    """The category constraint, the sector preference, and their fallbacks."""

    def _candidates(self) -> tuple[BuildingType, BuildingType]:
        urban_military = _building_type(
            name="Urban Military",
            land_development_category="urban",
            jobs_by_sector={"military": 100.0},
        )
        rural_office = _building_type(
            name="Rural Office",
            land_development_category="rural",
            jobs_by_sector={"office_services": 100.0},
        )
        return urban_military, rural_office

    def test_category_constraint_keeps_only_that_category(self) -> None:
        narrowed = require_same_category(list(self._candidates()), "urban")
        assert [building_type.name for building_type in narrowed] == ["Urban Military"]

    def test_a_category_no_candidate_names_matches_nothing(self) -> None:
        """The constraint never falls back to the nearest other category."""
        assert require_same_category(list(self._candidates()), "conservation") == []

    def test_an_unset_parcel_category_constrains_nothing(self) -> None:
        """A parcel that names no category — NULL or blank — keeps every candidate."""
        candidates = list(self._candidates())
        assert require_same_category(candidates, None) == candidates
        assert require_same_category(candidates, "") == candidates
        assert require_same_category(candidates, "   ") == candidates

    def test_a_blank_candidate_category_is_not_a_wildcard(self) -> None:
        uncategorised = _building_type(name="Mixed Use", land_development_category="")
        assert require_same_category([uncategorised], "urban") == []
        # an unset parcel category still admits it — that is the only case it can serve
        assert require_same_category([uncategorised], None) == [uncategorised]

    def test_sector_preference_narrows(self) -> None:
        narrowed = prefer_same_sector(list(self._candidates()), "office_services")
        assert [building_type.name for building_type in narrowed] == ["Rural Office"]

    def test_sector_preference_falls_back(self) -> None:
        candidates = list(self._candidates())
        assert prefer_same_sector(candidates, "agriculture") == candidates
        assert prefer_same_sector(candidates, None) == candidates

    def test_a_zero_share_declares_nothing(self) -> None:
        zeroed = _building_type(name="Zero", jobs_by_sector={"military": 0.0})
        assert prefer_same_sector([zeroed], "military") == [zeroed]


# The parcel column can be NULL, blank, padded or set; the form column is NOT
# NULL in the database, so it has no NULL case of its own. One entry per shape
# either runtime sees.
PARCEL_CATEGORIES: list[str | None] = [None, "", "   ", "urban", "urban ", "rural"]
FORM_CATEGORIES: list[str] = ["", "   ", "urban", " rural ", "conservation"]


@pytest.mark.models
class TestCategoryConstraintSqlMatchesPythonRule:
    """The predicate the fill model filters candidates with is the Python rule.

    Both runtimes apply the constraint — the paint surfaces in Python, the
    base-canvas fill model in a ``WHERE`` — and a parcel the two disagree about
    is a parcel that paints one way and imports as another.
    """

    def test_agrees_on_every_parcel_and_form_category(self, db) -> None:
        predicate = category_requirement_sql(parcel_prefix="s.", form_prefix="bf.")
        parcels = ", ".join(["(%s::text)"] * len(PARCEL_CATEGORIES))
        forms = ", ".join(["(%s::text)"] * len(FORM_CATEGORIES))
        # The predicate's own ``WHERE`` semantics: SQL's NULL is a dropped row,
        # not a false — ``CASE`` turns it into the same answer for the assert.
        # The interpolated text is the rule under test and every value is a
        # placeholder, so this is not injection-shaped.
        query = (
            "SELECT s.land_development_category, bf.land_development_category,"  # noqa: S608
            " CASE WHEN " + predicate + " THEN true ELSE false END"
            " FROM (VALUES " + parcels + ") AS s(land_development_category)"
            " CROSS JOIN (VALUES " + forms + ") AS bf(land_development_category)"
        )

        with connection.cursor() as cursor:
            cursor.execute(query, [*PARCEL_CATEGORIES, *FORM_CATEGORIES])
            rows = cursor.fetchall()

        assert len(rows) == len(PARCEL_CATEGORIES) * len(FORM_CATEGORIES)
        for parcel_category, form_category, admitted in rows:
            candidate = _building_type(
                name="Candidate",
                # A Building Type's column is NOT NULL: '' is what an unset one holds.
                land_development_category=form_category or "",
            )
            expected = bool(require_same_category([candidate], parcel_category))
            assert admitted is expected, (parcel_category, form_category)


@pytest.mark.models
class TestSectorVocabulary:
    """Reading a Building Type's declared sectors."""

    def test_non_canonical_keys_are_dropped(self) -> None:
        """A mix keyed by the old fixture's vocabulary matches no parcel column."""
        legacy = _building_type(
            name="Legacy", jobs_by_sector={"retail": 80, "food_service": 20}
        )
        assert declared_sectors(legacy) == {}

    def test_canonical_keys_survive(self) -> None:
        mixed = _building_type(
            name="Mixed",
            jobs_by_sector={"retail_services": 60.0, "restaurant": 40.0},
        )
        assert declared_sectors(mixed) == {"retail_services": 60.0, "restaurant": 40.0}

    def test_limited_to_the_canonical_sectors(self) -> None:
        partial = _building_type(
            name="Partial",
            jobs_by_sector={"office_services": 70.0, "warehousing": 30.0},
        )
        assert declared_sectors(partial) == {"office_services": 70.0}

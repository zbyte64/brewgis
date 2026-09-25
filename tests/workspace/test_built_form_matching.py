"""Tests for the built-form matching preferences (``built_forms.matching``)."""

from __future__ import annotations

from typing import Any

import pytest

from brewgis.workspace.built_forms.matching import declared_sectors
from brewgis.workspace.built_forms.matching import dominant_employment_sector
from brewgis.workspace.built_forms.matching import prefer_same_category
from brewgis.workspace.built_forms.matching import prefer_same_sector
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
    """The two narrowing preferences and their fallbacks."""

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

    def test_category_preference_narrows(self) -> None:
        narrowed = prefer_same_category(list(self._candidates()), "urban")
        assert [building_type.name for building_type in narrowed] == ["Urban Military"]

    def test_category_preference_falls_back(self) -> None:
        candidates = list(self._candidates())
        assert prefer_same_category(candidates, "conservation") == candidates
        assert prefer_same_category(candidates, "") == candidates
        assert prefer_same_category(candidates, None) == candidates

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

"""Tests for built forms models."""

from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.test import TestCase

from brewgis.workspace.built_forms.default_library import DEFAULT_BUILDING_TYPES
from brewgis.workspace.built_forms.default_library import RETIRED_LIBRARY_NAMES
from brewgis.workspace.built_forms.default_library import backfill_library_fields
from brewgis.workspace.built_forms.default_library import retire_library_entries
from brewgis.workspace.built_forms.default_library import seed_default_built_forms
from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.services.base_canvas_schema import EMPLOYMENT_SECTORS
from tests.factories import PaintedCanvasFactory
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory


@pytest.mark.models
class TestBuildingType(TestCase):
    """BuildingType model tests."""

    def setUp(self) -> None:
        self.workspace = WorkspaceFactory()

    def test_create_minimal(self) -> None:
        """Creating a BuildingType with just a name should work."""
        bt = BuildingType.objects.create(workspace=self.workspace, name="Test Type")
        self.assertEqual(str(bt), "Test Type")
        self.assertEqual(bt.household_size, 2.5)
        self.assertEqual(bt.vacancy_rate, 5.0)
        self.assertEqual(bt.parking_sqft_per_space, 300.0)
        self.assertEqual(bt.pass_by_trip_pct, 0.0)

    def test_unique_name_constraint(self) -> None:
        """Duplicate names should be rejected."""
        BuildingType.objects.create(workspace=self.workspace, name="Unique")
        with self.assertRaises(IntegrityError):
            BuildingType.objects.create(workspace=self.workspace, name="Unique")

    def test_create_full(self) -> None:
        """Creating a BuildingType with all fields set should work."""
        bt = BuildingType.objects.create(
            workspace=self.workspace,
            name="Full Test",
            description="A comprehensive test",
            du_per_acre=20.0,
            emp_per_acre=5.0,
            far=1.5,
            household_size=2.0,
            tenure_owner_pct=50.0,
            tenure_renter_pct=50.0,
            vacancy_rate=8.0,
            stories=3,
            footprint_per_unit=80.0,
            building_coverage=35.0,
            jobs_by_sector={"retail": 60, "office": 40},
            indoor_water_rate=200.0,
            outdoor_water_rate=150.0,
            irrigable_area_fraction=0.15,
            electricity_eui=70.0,
            gas_eui=90.0,
            vintage="post_2000",
            parking_spaces_per_unit=1.0,
            parking_spaces_per_1000sqft=2.0,
            parking_sqft_per_space=350.0,
            ite_land_use_code=220,
            trip_rate_override=5.0,
            pass_by_trip_pct=10.0,
        )
        self.assertEqual(bt.du_per_acre, 20.0)
        self.assertEqual(bt.emp_per_acre, 5.0)
        self.assertEqual(bt.jobs_by_sector, {"retail": 60, "office": 40})
        self.assertEqual(bt.get_vintage_display(), "Post-2000")

    def test_nullable_density_fields(self) -> None:
        """Employment-only building types should allow null residential fields."""
        bt = BuildingType.objects.create(
            workspace=self.workspace,
            name="Employment Only",
            du_per_acre=None,
            emp_per_acre=40.0,
        )
        self.assertIsNone(bt.du_per_acre)
        self.assertEqual(bt.emp_per_acre, 40.0)

    def test_str_representation(self) -> None:
        """__str__ should return the name."""
        bt = BuildingType.objects.create(workspace=self.workspace, name="Single-Family")
        self.assertEqual(str(bt), "Single-Family")


@pytest.mark.models
class TestPlaceType(TestCase):
    """PlaceType model tests."""

    def setUp(self) -> None:
        self.workspace = WorkspaceFactory()

    def test_create_minimal(self) -> None:
        """Creating a PlaceType with just a name should work."""
        pt = PlaceType.objects.create(workspace=self.workspace, name="Test Place")
        self.assertEqual(str(pt), "Test Place")
        self.assertEqual(pt.row_allocation_pct, 25.0)

    def test_unique_name_constraint(self) -> None:
        """Duplicate names should be rejected."""
        PlaceType.objects.create(workspace=self.workspace, name="Unique Place")
        with self.assertRaises(IntegrityError):
            PlaceType.objects.create(workspace=self.workspace, name="Unique Place")

    def test_create_with_all_fields(self) -> None:
        """Creating a PlaceType with all fields should work."""
        pt = PlaceType.objects.create(
            workspace=self.workspace,
            name="Urban Core",
            description="Dense downtown area",
            row_allocation_pct=40.0,
            block_size=80.0,
            street_pattern="grid",
        )
        self.assertEqual(pt.row_allocation_pct, 40.0)
        self.assertEqual(pt.block_size, 80.0)
        self.assertEqual(pt.street_pattern, "grid")
        self.assertEqual(pt.get_street_pattern_display(), "Grid")


@pytest.mark.models
class TestPlaceTypeBuildingTypeMix(TestCase):
    """PlaceTypeBuildingTypeMix model tests."""

    def setUp(self) -> None:
        self.workspace = WorkspaceFactory()
        self.bt = BuildingType.objects.create(workspace=self.workspace, name="Test BT")
        self.pt = PlaceType.objects.create(workspace=self.workspace, name="Test PT")

    def test_create_mix(self) -> None:
        """Creating a valid mix should work."""
        mix = PlaceTypeBuildingTypeMix.objects.create(
            place_type=self.pt,
            building_type=self.bt,
            percentage=50.0,
        )
        self.assertEqual(mix.percentage, 50.0)
        self.assertEqual(
            str(mix),
            "Test PT → Test BT (50.0%)",
        )

    def test_unique_constraint(self) -> None:
        """Duplicate (place_type, building_type) should be rejected."""
        PlaceTypeBuildingTypeMix.objects.create(
            place_type=self.pt,
            building_type=self.bt,
            percentage=30.0,
        )
        with self.assertRaises(IntegrityError):
            PlaceTypeBuildingTypeMix.objects.create(
                place_type=self.pt,
                building_type=self.bt,
                percentage=70.0,
            )

    def test_cascade_delete_building_type(self) -> None:
        """Deleting a BuildingType should cascade-delete its mixes."""
        mix = PlaceTypeBuildingTypeMix.objects.create(
            place_type=self.pt,
            building_type=self.bt,
            percentage=100.0,
        )
        self.bt.delete()
        self.assertFalse(
            PlaceTypeBuildingTypeMix.objects.filter(pk=mix.pk).exists(),
        )

    def test_cascade_delete_place_type(self) -> None:
        """Deleting a PlaceType should cascade-delete its mixes."""
        mix = PlaceTypeBuildingTypeMix.objects.create(
            place_type=self.pt,
            building_type=self.bt,
            percentage=100.0,
        )
        self.pt.delete()
        self.assertFalse(
            PlaceTypeBuildingTypeMix.objects.filter(pk=mix.pk).exists(),
        )

    def test_related_name_place_type(self) -> None:
        """PlaceType should have building_type_mixes related name."""
        PlaceTypeBuildingTypeMix.objects.create(
            place_type=self.pt,
            building_type=self.bt,
            percentage=100.0,
        )
        self.assertEqual(self.pt.building_type_mixes.count(), 1)

    def test_related_name_building_type(self) -> None:
        """BuildingType should have place_type_mixes related name."""
        PlaceTypeBuildingTypeMix.objects.create(
            place_type=self.pt,
            building_type=self.bt,
            percentage=100.0,
        )
        self.assertEqual(self.bt.place_type_mixes.count(), 1)

    def test_ordering(self) -> None:
        """Mix results should be ordered by (place_type, building_type)."""
        bt2 = BuildingType.objects.create(workspace=self.workspace, name="BT B")
        PlaceTypeBuildingTypeMix.objects.create(
            place_type=self.pt,
            building_type=bt2,
            percentage=30.0,
        )
        PlaceTypeBuildingTypeMix.objects.create(
            place_type=self.pt,
            building_type=self.bt,
            percentage=70.0,
        )
        mixes = PlaceTypeBuildingTypeMix.objects.filter(place_type=self.pt)
        self.assertEqual(mixes[0].building_type.name, "BT B")
        self.assertEqual(mixes[1].building_type.name, "Test BT")


@pytest.mark.models
class TestDefaultBuiltFormsLibrary(TestCase):
    """Default library seeding — additive — and the category/sector backfill."""

    def setUp(self) -> None:
        self.workspace = WorkspaceFactory()
        self.library_names = {entry["name"] for entry in DEFAULT_BUILDING_TYPES}
        first = DEFAULT_BUILDING_TYPES[0]
        self.library_name = first["name"]
        self.library_category = first["land_development_category"]
        with_sectors = next(
            entry for entry in DEFAULT_BUILDING_TYPES if entry["jobs_by_sector"]
        )
        self.library_with_sectors = with_sectors["name"]
        self.library_jobs_by_sector = with_sectors["jobs_by_sector"]
        self.library_category_of_sectors = with_sectors["land_development_category"]

    def test_seed_adds_only_what_is_missing(self) -> None:
        """An existing catalogue is completed, never rewritten, and re-seeding is a no-op."""
        kept = BuildingType.objects.create(
            workspace=self.workspace,
            name=self.library_name,
            du_per_acre=123.0,
        )
        own = BuildingType.objects.create(
            workspace=self.workspace, name="Hand-authored Type"
        )

        created = seed_default_built_forms(self.workspace)

        self.assertEqual(created, len(DEFAULT_BUILDING_TYPES) - 1)
        self.assertEqual(seed_default_built_forms(self.workspace), 0)
        kept.refresh_from_db()
        self.assertEqual(kept.du_per_acre, 123.0)
        self.assertEqual(
            BuildingType.objects.filter(workspace=self.workspace).count(),
            len(DEFAULT_BUILDING_TYPES) + 1,
        )
        # every library name is present exactly once, and the workspace's own
        # type is still there
        names = list(
            BuildingType.objects.filter(workspace=self.workspace).values_list(
                "name", flat=True
            )
        )
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(self.library_names.issubset(set(names)))
        self.assertIn(own.name, names)

    def test_backfill_realigns_library_named_types(self) -> None:
        """A type sharing a library name is aligned to that entry."""
        stale = BuildingType.objects.create(
            workspace=self.workspace,
            name=self.library_with_sectors,
            land_development_category="conservation",
            jobs_by_sector={"retail": 80, "food_service": 20},
            household_size=9.0,
            vacancy_rate=42.0,
        )
        own = BuildingType.objects.create(
            workspace=self.workspace,
            name="Hand-authored Type",
            land_development_category="rural",
            jobs_by_sector={"military": 100.0},
            household_size=9.0,
        )

        self.assertEqual(backfill_library_fields(self.workspace), 1)

        stale.refresh_from_db()
        own.refresh_from_db()
        self.assertEqual(stale.jobs_by_sector, self.library_jobs_by_sector)
        self.assertEqual(
            stale.land_development_category, self.library_category_of_sectors
        )
        # the library entry has no dwellings, so the row it stands for must not
        # claim a household size either
        self.assertIsNone(stale.household_size)
        self.assertIsNone(stale.vacancy_rate)
        # a profile the library does not name is never touched
        self.assertEqual(own.land_development_category, "rural")
        self.assertEqual(own.jobs_by_sector, {"military": 100.0})
        self.assertEqual(own.household_size, 9.0)
        self.assertEqual(backfill_library_fields(self.workspace), 0)


@pytest.mark.models
class TestRetiredLibraryEntries(TestCase):
    """A name the library dropped is deleted where nothing points at it."""

    def setUp(self) -> None:
        self.workspace = WorkspaceFactory()
        self.scenario = ScenarioFactory(
            workspace=self.workspace, scenario_type=ScenarioType.ALTERNATIVE
        )
        self.retired_name = next(iter(RETIRED_LIBRARY_NAMES))

    def test_retired_entry_is_deleted_when_unreferenced(self) -> None:
        BuildingType.objects.create(workspace=self.workspace, name=self.retired_name)
        keep = BuildingType.objects.create(
            workspace=self.workspace, name="Hand-authored Type"
        )

        self.assertEqual(retire_library_entries(self.workspace), 1)

        assert not BuildingType.objects.filter(
            workspace=self.workspace, name=self.retired_name
        ).exists()
        assert BuildingType.objects.filter(pk=keep.pk).exists()

    def test_retired_entry_a_paint_names_is_kept(self) -> None:
        building_type = BuildingType.objects.create(
            workspace=self.workspace, name=self.retired_name
        )
        PaintedCanvasFactory(
            scenario=self.scenario,
            column_name="built_form_key",
            painted_text_value=self.retired_name,
        )

        self.assertEqual(retire_library_entries(self.workspace), 0)

        assert BuildingType.objects.filter(pk=building_type.pk).exists()


@pytest.mark.models
class TestDefaultLibraryEntries(TestCase):
    """What each library entry claims about its own land use."""

    def test_entries_without_dwellings_claim_no_households(self) -> None:
        """An office, a warehouse or a crop type has no household size."""
        for entry in DEFAULT_BUILDING_TYPES:
            if entry["du_per_acre"]:
                continue
            assert entry["household_size"] is None, entry["name"]
            assert entry["vacancy_rate"] is None, entry["name"]

    def test_dwelling_entries_keep_a_household_size(self) -> None:
        """A type that houses people still says how many live in a unit."""
        for entry in DEFAULT_BUILDING_TYPES:
            if not entry["du_per_acre"]:
                continue
            assert entry["household_size"], entry["name"]

    def test_no_two_entries_share_a_name(self) -> None:
        names = [entry["name"] for entry in DEFAULT_BUILDING_TYPES]
        assert len(names) == len(set(names))

    def test_sector_mixes_use_the_parcel_sector_vocabulary(self) -> None:
        """A mix a parcel column cannot be compared with would never match."""
        for entry in DEFAULT_BUILDING_TYPES:
            unknown = set(entry["jobs_by_sector"]) - set(EMPLOYMENT_SECTORS)
            assert not unknown, (entry["name"], unknown)

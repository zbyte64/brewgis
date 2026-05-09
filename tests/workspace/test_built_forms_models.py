"""Tests for built forms models."""

from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.test import TestCase

from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix


@pytest.mark.models
class TestBuildingType(TestCase):
    """BuildingType model tests."""

    def test_create_minimal(self) -> None:
        """Creating a BuildingType with just a name should work."""
        bt = BuildingType.objects.create(name="Test Type")
        self.assertEqual(str(bt), "Test Type")
        self.assertEqual(bt.household_size, 2.5)
        self.assertEqual(bt.vacancy_rate, 5.0)
        self.assertEqual(bt.parking_sqft_per_space, 300.0)
        self.assertEqual(bt.pass_by_trip_pct, 0.0)

    def test_unique_name_constraint(self) -> None:
        """Duplicate names should be rejected."""
        BuildingType.objects.create(name="Unique")
        with self.assertRaises(IntegrityError):
            BuildingType.objects.create(name="Unique")

    def test_create_full(self) -> None:
        """Creating a BuildingType with all fields set should work."""
        bt = BuildingType.objects.create(
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
            name="Employment Only",
            du_per_acre=None,
            emp_per_acre=40.0,
        )
        self.assertIsNone(bt.du_per_acre)
        self.assertEqual(bt.emp_per_acre, 40.0)

    def test_str_representation(self) -> None:
        """__str__ should return the name."""
        bt = BuildingType.objects.create(name="Single-Family")
        self.assertEqual(str(bt), "Single-Family")


@pytest.mark.models
class TestPlaceType(TestCase):
    """PlaceType model tests."""

    def test_create_minimal(self) -> None:
        """Creating a PlaceType with just a name should work."""
        pt = PlaceType.objects.create(name="Test Place")
        self.assertEqual(str(pt), "Test Place")
        self.assertEqual(pt.row_allocation_pct, 25.0)

    def test_unique_name_constraint(self) -> None:
        """Duplicate names should be rejected."""
        PlaceType.objects.create(name="Unique Place")
        with self.assertRaises(IntegrityError):
            PlaceType.objects.create(name="Unique Place")

    def test_create_with_all_fields(self) -> None:
        """Creating a PlaceType with all fields should work."""
        pt = PlaceType.objects.create(
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
        self.bt = BuildingType.objects.create(name="Test BT")
        self.pt = PlaceType.objects.create(name="Test PT")

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
        bt2 = BuildingType.objects.create(name="BT B")
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

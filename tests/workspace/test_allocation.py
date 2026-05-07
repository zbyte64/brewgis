"""Tests for the allocation engine."""
from __future__ import annotations

from django.test import TestCase

from brewgis.workspace.built_forms.allocation import AllocationEngine
from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix


class TestAllocationBuildingType(TestCase):
    """Allocation engine tests for single BuildingType."""

    def setUp(self) -> None:
        self.residential = BuildingType.objects.create(
            name="Residential Test",
            du_per_acre=10.0,
            emp_per_acre=0.0,
            far=0.8,
            household_size=2.5,
            vacancy_rate=5.0,
            stories=2,
            building_coverage=30.0,
            indoor_water_rate=200.0,
            outdoor_water_rate=300.0,
            irrigable_area_fraction=0.2,
            electricity_eui=70.0,
            gas_eui=100.0,
            parking_spaces_per_unit=1.5,
            parking_spaces_per_1000sqft=0.0,
            trip_rate_override=5.0,
        )
        self.employment = BuildingType.objects.create(
            name="Employment Test",
            du_per_acre=None,
            emp_per_acre=50.0,
            far=0.5,
            household_size=2.5,
            vacancy_rate=5.0,
            stories=1,
            building_coverage=40.0,
            jobs_by_sector={"retail": 100},
            indoor_water_rate=None,
            outdoor_water_rate=200.0,
            electricity_eui=120.0,
            gas_eui=80.0,
            parking_spaces_per_unit=None,
            parking_spaces_per_1000sqft=4.0,
            trip_rate_override=None,
            ite_land_use_code=820,
        )
        self.mixed = BuildingType.objects.create(
            name="Mixed Use Test",
            du_per_acre=20.0,
            emp_per_acre=30.0,
            far=2.0,
            household_size=2.0,
            vacancy_rate=8.0,
            stories=4,
            building_coverage=50.0,
            jobs_by_sector={"retail": 40, "office": 60},
            indoor_water_rate=180.0,
            outdoor_water_rate=50.0,
            electricity_eui=80.0,
            gas_eui=60.0,
            parking_spaces_per_unit=1.0,
            parking_spaces_per_1000sqft=2.0,
            trip_rate_override=4.0,
        )

    def test_developable_acres_calculation(self) -> None:
        """ROW reduction should compute correctly."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.residential,
            row_allocation_pct=25.0,
        )
        self.assertAlmostEqual(result.developable_acres, 7.5)
        self.assertAlmostEqual(result.row_acres, 2.5)

    def test_dwelling_units(self) -> None:
        """Dwelling units should be developable_acres * du_per_acre."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.residential,
            row_allocation_pct=20.0,
        )
        developable = 10.0 * 0.8  # 8.0 acres
        expected_du = developable * 10.0  # 80.0 units
        self.assertAlmostEqual(result.total_dwelling_units, expected_du)

    def test_population_and_households(self) -> None:
        """Population and households should be derived from dwelling units."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.residential,
            row_allocation_pct=25.0,
        )
        developable = 7.5
        units = developable * 10.0  # 75 units
        expected_pop = units * 2.5  # 187.5
        expected_hh = units * (1.0 - 0.05)  # 71.25
        self.assertAlmostEqual(result.total_population, expected_pop)
        self.assertAlmostEqual(result.total_households, expected_hh)

    def test_employment_generation(self) -> None:
        """Employment should be 0 for residential building types."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.residential,
            row_allocation_pct=25.0,
        )
        self.assertEqual(result.total_employment, 0.0)

    def test_employment_present(self) -> None:
        """Employment building type should generate jobs."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.employment,
            row_allocation_pct=25.0,
        )
        developable = 7.5
        expected_emp = developable * 50.0  # 375 jobs
        self.assertAlmostEqual(result.total_employment, expected_emp)

    def test_employment_by_sector(self) -> None:
        """Jobs should be split by sector."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.mixed,
            row_allocation_pct=25.0,
        )
        developable = 7.5
        total_jobs = developable * 30.0  # 225 jobs
        expected_retail = total_jobs * 0.4  # 90
        expected_office = total_jobs * 0.6  # 135
        self.assertAlmostEqual(
            result.employment_by_sector["retail"],
            expected_retail,
        )
        self.assertAlmostEqual(
            result.employment_by_sector["office"],
            expected_office,
        )

    def test_floor_area_via_far(self) -> None:
        """Floor area should be computed from FAR when available."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.mixed,
            row_allocation_pct=25.0,
        )
        developable_sqft = 7.5 * 43560.0
        developable_m2 = developable_sqft * 0.092903
        expected_fa = developable_m2 * 2.0  # FAR = 2.0
        self.assertAlmostEqual(result.floor_area_m2, expected_fa, delta=1.0)

    def test_water_indoor(self) -> None:
        """Indoor water should be population * rate * 365."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.residential,
            row_allocation_pct=25.0,
        )
        developable = 7.5
        units = developable * 10.0
        pop = units * 2.5
        expected_water = pop * 200.0 * 365.0
        self.assertAlmostEqual(result.water_demand_indoor_l, expected_water)

    def test_water_indoor_zero_for_employment(self) -> None:
        """Employment building type without indoor rate should have 0 indoor water."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.employment,
            row_allocation_pct=25.0,
        )
        self.assertEqual(result.water_demand_indoor_l, 0.0)

    def test_energy(self) -> None:
        """Energy should be floor_area * EUI."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.residential,
            row_allocation_pct=25.0,
        )
        developable_sqft = 7.5 * 43560.0
        developable_m2 = developable_sqft * 0.092903
        floor_area_m2 = developable_m2 * 0.8  # FAR = 0.8
        expected_elec = floor_area_m2 * 70.0
        expected_gas = floor_area_m2 * 100.0
        self.assertAlmostEqual(
            result.energy_electricity_kwh,
            expected_elec,
            delta=100.0,
        )
        self.assertAlmostEqual(
            result.energy_gas_kwh,
            expected_gas,
            delta=100.0,
        )

    def test_trips(self) -> None:
        """Trips should be units * trip_rate_override."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.residential,
            row_allocation_pct=25.0,
        )
        developable = 7.5
        units = developable * 10.0
        expected_trips = units * 5.0
        self.assertAlmostEqual(result.trips_per_day, expected_trips)

    def test_parking(self) -> None:
        """Parking should combine unit-based and floor-area-based requirements."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.mixed,
            row_allocation_pct=25.0,
        )
        developable = 7.5
        units = developable * 20.0
        # Spaces from units
        spaces_units = units * 1.0
        # Spaces from non-res floor area
        result_with_far = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.mixed,
            row_allocation_pct=0.0,  # Use 0% ROW to simplify
        )
        self.assertGreater(result_with_far.parking_spaces, 0)

    def test_zero_du_per_acre(self) -> None:
        """Employment-only building type should have 0 dwelling units."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.employment,
            row_allocation_pct=25.0,
        )
        self.assertEqual(result.total_dwelling_units, 0.0)

    def test_hundred_percent_row(self) -> None:
        """100% ROW allocation should yield 0 developable area."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.residential,
            row_allocation_pct=100.0,
        )
        self.assertEqual(result.developable_acres, 0.0)
        self.assertEqual(result.total_dwelling_units, 0.0)

    def test_zero_parcel_area(self) -> None:
        """Zero acre parcel should yield zero outputs."""
        result = AllocationEngine.allocation_building_type(
            parcel_acres=0.0,
            building_type=self.mixed,
            row_allocation_pct=25.0,
        )
        self.assertEqual(result.developable_acres, 0.0)
        self.assertEqual(result.total_dwelling_units, 0.0)
        self.assertEqual(result.total_population, 0.0)
        self.assertEqual(result.total_employment, 0.0)

    def test_allocation_result_defaults(self) -> None:
        """AllocationResult should have sensible defaults including empty dicts/lists."""
        from brewgis.workspace.built_forms.allocation import AllocationResult

        result = AllocationResult()
        self.assertEqual(result.employment_by_sector, {})
        self.assertEqual(result.per_building_type_breakdown, [])
        self.assertEqual(result.developable_acres, 0.0)
        self.assertEqual(result.trips_per_day, 0.0)


class TestAllocationPlaceType(TestCase):
    """Allocation engine tests for PlaceType with building type mix."""

    def setUp(self) -> None:
        self.bt_single = BuildingType.objects.create(
            name="Single-Family",
            du_per_acre=5.0,
            emp_per_acre=0.0,
            far=0.45,
            household_size=2.6,
            vacancy_rate=4.0,
            indoor_water_rate=240.0,
            outdoor_water_rate=400.0,
            electricity_eui=75.0,
            gas_eui=110.0,
            parking_spaces_per_unit=2.0,
            trip_rate_override=9.5,
        )
        self.bt_townhouse = BuildingType.objects.create(
            name="Townhouse",
            du_per_acre=12.0,
            emp_per_acre=0.0,
            far=0.7,
            household_size=2.4,
            vacancy_rate=5.0,
            indoor_water_rate=220.0,
            outdoor_water_rate=200.0,
            electricity_eui=70.0,
            gas_eui=100.0,
            parking_spaces_per_unit=1.5,
            trip_rate_override=6.5,
        )
        self.bt_retail = BuildingType.objects.create(
            name="Neighborhood Retail",
            du_per_acre=None,
            emp_per_acre=25.0,
            far=0.5,
            household_size=2.5,
            vacancy_rate=5.0,
            jobs_by_sector={"retail": 80, "food_service": 20},
            indoor_water_rate=None,
            outdoor_water_rate=200.0,
            electricity_eui=120.0,
            gas_eui=80.0,
            parking_spaces_per_unit=None,
            parking_spaces_per_1000sqft=4.0,
            trip_rate_override=None,
            ite_land_use_code=820,
        )

        self.place_type = PlaceType.objects.create(
            name="Test Neighborhood",
            row_allocation_pct=30.0,
            block_size=120.0,
            street_pattern="grid",
        )

        PlaceTypeBuildingTypeMix.objects.create(
            place_type=self.place_type,
            building_type=self.bt_single,
            percentage=50.0,
        )
        PlaceTypeBuildingTypeMix.objects.create(
            place_type=self.place_type,
            building_type=self.bt_townhouse,
            percentage=30.0,
        )
        PlaceTypeBuildingTypeMix.objects.create(
            place_type=self.place_type,
            building_type=self.bt_retail,
            percentage=20.0,
        )

    def test_place_type_row_reduction(self) -> None:
        """PlaceType allocation should apply ROW reduction first."""
        result = AllocationEngine.allocation_place_type(
            parcel_acres=40.0,
            place_type=self.place_type,
        )
        self.assertAlmostEqual(result.row_acres, 12.0)  # 40 * 0.3
        self.assertAlmostEqual(result.developable_acres, 28.0)  # 40 * 0.7

    def test_place_type_aggregates(self) -> None:
        """PlaceType allocation should sum per-building-type results."""
        result = AllocationEngine.allocation_place_type(
            parcel_acres=40.0,
            place_type=self.place_type,
        )
        # Developable = 28 acres
        # Single-family (50%): 14 acres * 5 du/ac = 70 du
        # Townhouse (30%): 8.4 acres * 12 du/ac = 100.8 du
        expected_du = (14.0 * 5.0) + (8.4 * 12.0)
        self.assertAlmostEqual(
            result.total_dwelling_units,
            expected_du,
            delta=0.1,
        )

    def test_place_type_employment(self) -> None:
        """PlaceType should aggregate employment from its building types."""
        result = AllocationEngine.allocation_place_type(
            parcel_acres=40.0,
            place_type=self.place_type,
        )
        # Single-family: 0 emp
        # Townhouse: 0 emp
        # Retail (20%): 5.6 acres * 25 emp/ac = 140 jobs
        expected_emp = 5.6 * 25.0
        self.assertAlmostEqual(result.total_employment, expected_emp, delta=0.1)

    def test_place_type_breakdown(self) -> None:
        """PlaceType allocation should include per-building-type breakdown."""
        result = AllocationEngine.allocation_place_type(
            parcel_acres=40.0,
            place_type=self.place_type,
        )
        self.assertEqual(len(result.per_building_type_breakdown), 3)
        names = {b["building_type_name"] for b in result.per_building_type_breakdown}
        self.assertIn("Single-Family", names)
        self.assertIn("Townhouse", names)
        self.assertIn("Neighborhood Retail", names)

    def test_place_type_total_matches_breakdown(self) -> None:
        """Sum of breakdown should match total."""
        result = AllocationEngine.allocation_place_type(
            parcel_acres=40.0,
            place_type=self.place_type,
        )
        sum_du = sum(b["dwelling_units"] for b in result.per_building_type_breakdown)
        self.assertAlmostEqual(result.total_dwelling_units, sum_du, delta=0.1)

    def test_single_building_type_place_type(self) -> None:
        """PlaceType with 100% a single building type should match direct allocation."""
        pt = PlaceType.objects.create(
            name="Single Mix",
            row_allocation_pct=25.0,
        )
        PlaceTypeBuildingTypeMix.objects.create(
            place_type=pt,
            building_type=self.bt_single,
            percentage=100.0,
        )

        direct = AllocationEngine.allocation_building_type(
            parcel_acres=10.0,
            building_type=self.bt_single,
            row_allocation_pct=25.0,
        )
        via_pt = AllocationEngine.allocation_place_type(
            parcel_acres=10.0,
            place_type=pt,
        )

        self.assertAlmostEqual(
            via_pt.total_dwelling_units,
            direct.total_dwelling_units,
            delta=0.1,
        )
        self.assertAlmostEqual(
            via_pt.total_population,
            direct.total_population,
            delta=0.1,
        )

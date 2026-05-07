"""Allocation engine — pure computation for built form outputs.

Computes dwelling units, population, employment, water, energy,
trips, and parking from parcel area and built form parameters.

All functions are pure: no DB queries, no side effects.
Callers pass model instances (BuildingType or PlaceType) or dicts.

Unit conventions:
    - Area: acres (input), converted internally
    - Length: meters
    - Volume: liters
    - Energy: kWh
    - Parking area: m²
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brewgis.workspace.built_forms.models import BuildingType
    from brewgis.workspace.built_forms.models import PlaceType


# Conversion factors
SQFT_PER_ACRE = 43560.0
SQFT_TO_SQM = 0.092903


@dataclass
class AllocationResult:
    """Complete allocation output for one parcel + built form combination."""

    developable_acres: float = 0.0
    row_acres: float = 0.0

    total_dwelling_units: float = 0.0
    total_population: float = 0.0
    total_households: float = 0.0

    total_employment: float = 0.0
    employment_by_sector: dict[str, float] = field(default_factory=dict)

    floor_area_m2: float = 0.0
    building_footprint_m2: float = 0.0

    water_demand_indoor_l: float = 0.0
    water_demand_outdoor_l: float = 0.0

    energy_electricity_kwh: float = 0.0
    energy_gas_kwh: float = 0.0

    trips_per_day: float = 0.0
    parking_spaces: float = 0.0
    parking_area_m2: float = 0.0

    # PlaceType breakdown (one entry per BuildingType in the mix)
    per_building_type_breakdown: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Coerce lists to avoid shared-reference issues."""
        if self.per_building_type_breakdown is None:
            self.per_building_type_breakdown = []
        if self.employment_by_sector is None:
            self.employment_by_sector = {}


class AllocationEngine:
    """Stateless allocation engine.

    Usage::
        bt = BuildingType.objects.get(name="Single-Family Detached")
        result = AllocationEngine.allocation_building_type(
            parcel_acres=10.0, building_type=bt
        )

        pt = PlaceType.objects.get(name="Suburban Neighborhood")
        result = AllocationEngine.allocation_place_type(
            parcel_acres=40.0, place_type=pt
        )
    """

    @staticmethod
    def allocation_building_type(
        parcel_acres: float,
        building_type: BuildingType,
        row_allocation_pct: float = 25.0,
    ) -> AllocationResult:
        """Compute allocation for a single BuildingType on a parcel.

        Args:
            parcel_acres: Total parcel area in acres.
            building_type: A BuildingType model instance.
            row_allocation_pct: Percent of area lost to right-of-way (0-100).

        Returns:
            An AllocationResult with all computed fields.
        """
        result = AllocationResult()

        # 1. ROW reduction
        developable_acres = parcel_acres * (1.0 - row_allocation_pct / 100.0)
        result.row_acres = parcel_acres - developable_acres
        result.developable_acres = developable_acres

        developable_sqft = developable_acres * SQFT_PER_ACRE

        # 2. Density — dwelling units
        du_per_acre = building_type.du_per_acre
        if du_per_acre is not None and du_per_acre > 0:
            result.total_dwelling_units = developable_acres * du_per_acre
        else:
            result.total_dwelling_units = 0.0

        # 3. Population & households
        units = result.total_dwelling_units
        household_size = building_type.household_size or 2.5
        vacancy = (building_type.vacancy_rate or 5.0) / 100.0

        result.total_population = units * household_size
        result.total_households = units * (1.0 - vacancy)

        # 4. Employment
        emp_per_acre = building_type.emp_per_acre
        if emp_per_acre is not None and emp_per_acre > 0:
            result.total_employment = developable_acres * emp_per_acre
        else:
            result.total_employment = 0.0

        # Employment by sector
        jobs_by_sector = building_type.jobs_by_sector or {}
        total_jobs = result.total_employment
        if total_jobs > 0 and jobs_by_sector:
            sector_total = sum(jobs_by_sector.values())
            if sector_total > 0:
                for sector, pct in jobs_by_sector.items():
                    result.employment_by_sector[sector] = total_jobs * (pct / sector_total)

        # 5. Floor area
        far = building_type.far
        if far is not None and far > 0:
            result.floor_area_m2 = developable_acres * SQFT_PER_ACRE * SQFT_TO_SQM * far
        elif building_type.stories and building_type.footprint_per_unit and units > 0:
            footprint_m2 = units * building_type.footprint_per_unit
            result.floor_area_m2 = footprint_m2 * building_type.stories
            result.building_footprint_m2 = footprint_m2
        elif building_type.building_coverage and building_type.stories:
            coverage_pct = building_type.building_coverage / 100.0
            site_area_m2 = developable_sqft * SQFT_TO_SQM
            result.building_footprint_m2 = site_area_m2 * coverage_pct
            result.floor_area_m2 = result.building_footprint_m2 * building_type.stories
        else:
            result.floor_area_m2 = 0.0

        # If footprint not computed above but FAR was used, estimate from density
        if result.building_footprint_m2 == 0.0 and result.floor_area_m2 > 0:
            # Use coverage ratio if available
            if building_type.building_coverage:
                site_area_m2 = developable_sqft * SQFT_TO_SQM
                result.building_footprint_m2 = site_area_m2 * (building_type.building_coverage / 100.0)

        # 6. Water
        indoor_rate = building_type.indoor_water_rate
        if indoor_rate is not None and indoor_rate > 0 and result.total_population > 0:
            result.water_demand_indoor_l = result.total_population * indoor_rate * 365.0

        outdoor_rate = building_type.outdoor_water_rate
        if outdoor_rate is not None and outdoor_rate > 0:
            site_area_m2 = developable_sqft * SQFT_TO_SQM
            irrigable_frac = building_type.irrigable_area_fraction or 0.0
            non_building_area = site_area_m2 - result.building_footprint_m2
            result.water_demand_outdoor_l = non_building_area * irrigable_frac * outdoor_rate

        # 7. Energy
        if building_type.electricity_eui is not None and result.floor_area_m2 > 0:
            result.energy_electricity_kwh = result.floor_area_m2 * building_type.electricity_eui
        if building_type.gas_eui is not None and result.floor_area_m2 > 0:
            result.energy_gas_kwh = result.floor_area_m2 * building_type.gas_eui

        # 8. Trips
        ite_rate = building_type.trip_rate_override
        if ite_rate is None and building_type.ite_land_use_code is not None:
            # Default ITE rates by land use code — simplified fallback
            # In production these would come from a reference table
            pass
        if ite_rate is not None and units > 0:
            result.trips_per_day = units * ite_rate

        # 9. Parking
        floor_area_1000sqft = (result.floor_area_m2 / SQFT_TO_SQM) / 1000.0
        spaces_from_units = (building_type.parking_spaces_per_unit or 0.0) * units
        spaces_from_floor = (building_type.parking_spaces_per_1000sqft or 0.0) * floor_area_1000sqft
        result.parking_spaces = spaces_from_units + spaces_from_floor
        parking_sqft_per = building_type.parking_sqft_per_space or 300.0
        result.parking_area_m2 = result.parking_spaces * parking_sqft_per * SQFT_TO_SQM

        return result

    @staticmethod
    def allocation_place_type(
        parcel_acres: float,
        place_type: PlaceType,
    ) -> AllocationResult:
        """Compute allocation for a PlaceType by aggregating its building type mixes.

        Args:
            parcel_acres: Total parcel area in acres.
            place_type: A PlaceType model instance with prefetched building_type_mixes.

        Returns:
            An AllocationResult with aggregated totals + per-type breakdown.
        """
        row_pct = place_type.row_allocation_pct or 25.0
        developable_acres = parcel_acres * (1.0 - row_pct / 100.0)
        row_acres = parcel_acres - developable_acres

        result = AllocationResult(
            developable_acres=developable_acres,
            row_acres=row_acres,
        )

        mixes = list(place_type.building_type_mixes.select_related("building_type").all())
        total_pct = sum(m.percentage for m in mixes) if mixes else 100.0

        for mix in mixes:
            bt = mix.building_type
            pct = mix.percentage / total_pct if total_pct > 0 else 0.0
            bt_acres = developable_acres * pct

            sub = AllocationEngine.allocation_building_type(
                parcel_acres=bt_acres,  # Already ROW-adjusted within the sub-alloc
                building_type=bt,
                row_allocation_pct=0.0,  # ROW already accounted for at PlaceType level
            )

            # Accumulate
            result.total_dwelling_units += sub.total_dwelling_units
            result.total_population += sub.total_population
            result.total_households += sub.total_households
            result.total_employment += sub.total_employment
            result.floor_area_m2 += sub.floor_area_m2
            result.building_footprint_m2 += sub.building_footprint_m2
            result.water_demand_indoor_l += sub.water_demand_indoor_l
            result.water_demand_outdoor_l += sub.water_demand_outdoor_l
            result.energy_electricity_kwh += sub.energy_electricity_kwh
            result.energy_gas_kwh += sub.energy_gas_kwh
            result.trips_per_day += sub.trips_per_day
            result.parking_spaces += sub.parking_spaces
            result.parking_area_m2 += sub.parking_area_m2

            for sector, val in sub.employment_by_sector.items():
                result.employment_by_sector[sector] = (
                    result.employment_by_sector.get(sector, 0.0) + val
                )

            result.per_building_type_breakdown.append({
                "building_type_name": bt.name,
                "building_type_id": bt.pk,
                "percentage": mix.percentage,
                "acres": bt_acres,
                "dwelling_units": sub.total_dwelling_units,
                "population": sub.total_population,
                "employment": sub.total_employment,
                "floor_area_m2": sub.floor_area_m2,
            })

        return result

    @staticmethod
    def allocation_building_type_on_parcel(
        parcel_acres: float,
        building_type: BuildingType,
        row_allocation_pct: float = 25.0,
    ) -> AllocationResult:
        """Alias for :meth:`allocation_building_type`."""
        return AllocationEngine.allocation_building_type(
            parcel_acres=parcel_acres,
            building_type=building_type,
            row_allocation_pct=row_allocation_pct,
        )

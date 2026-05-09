"""Models for built forms library — BuildingTypes, PlaceTypes, and their mix."""

from __future__ import annotations

from django.db import models


class VintageChoices(models.TextChoices):
    """Building vintage categories for energy modeling."""

    PRE_1970 = "pre_1970", "Pre-1970"
    _1970_2000 = "1970_2000", "1970–2000"
    POST_2000 = "post_2000", "Post-2000"
    NEW_CONSTRUCTION = "new", "New Construction"


class StreetPatternChoices(models.TextChoices):
    """Street pattern categories for PlaceTypes."""

    GRID = "grid", "Grid"
    CUL_DE_SAC = "cul_de_sac", "Cul-de-Sac"
    LOOP = "loop", "Loop"
    HYBRID = "hybrid", "Hybrid"


class BuildingType(models.Model):
    """A built form archetype with physical, demographic, and resource parameters."""

    # Identity
    name = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True, default="")

    # Density
    du_per_acre = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Dwelling units per acre",
        help_text="Residential density (net). Null = no residential.",
    )
    emp_per_acre = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Employment per acre",
        help_text="Job density (net). Null = no employment.",
    )
    far = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Floor area ratio",
        help_text="Gross floor area ÷ site area.",
    )

    # Housing / Household
    household_size = models.FloatField(
        blank=True,
        default=2.5,
        verbose_name="Household size",
        help_text="Average persons per household.",
    )
    tenure_owner_pct = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Owner occupancy (%)",
    )
    tenure_renter_pct = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Renter occupancy (%)",
    )
    vacancy_rate = models.FloatField(
        blank=True,
        default=5.0,
        verbose_name="Vacancy rate (%)",
        help_text="Percent of dwelling units vacant.",
    )

    # Physical form
    stories = models.IntegerField(
        blank=True,
        null=True,
        verbose_name="Stories",
        help_text="Typical number of stories.",
    )
    footprint_per_unit = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Footprint per unit (m²)",
        help_text="Average building footprint per dwelling unit.",
    )
    building_coverage = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Building coverage (%)",
        help_text="Percent of site area covered by buildings.",
    )

    # Employment mix
    jobs_by_sector = models.JSONField(
        blank=True,
        default=dict,
        verbose_name="Jobs by sector",
        help_text="Dict of sector → percentage of total employment.",
    )

    # Water
    indoor_water_rate = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Indoor water use (L/person/day)",
    )
    outdoor_water_rate = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Outdoor water use (L/m²/year)",
    )
    irrigable_area_fraction = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Irrigable area fraction",
        help_text="Fraction of open space that is irrigated.",
    )

    # Energy
    electricity_eui = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Electricity EUI (kWh/m²/yr)",
        help_text="Energy use intensity for electricity.",
    )
    gas_eui = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Gas EUI (kWh/m²/yr)",
        help_text="Energy use intensity for natural gas.",
    )
    vintage = models.CharField(
        max_length=32,
        choices=VintageChoices,
        blank=True,
        default="",
        verbose_name="Building vintage",
        help_text="Approximate construction era for energy modeling.",
    )

    # Parking
    parking_spaces_per_unit = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Parking spaces per dwelling unit",
    )
    parking_spaces_per_1000sqft = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Parking spaces per 1,000 ft² of non-res floor area",
    )
    parking_sqft_per_space = models.FloatField(
        blank=True,
        default=300.0,
        verbose_name="Parking area per space (ft²)",
        help_text="Square feet per parking space including aisles.",
    )

    # Trip generation
    ite_land_use_code = models.IntegerField(
        blank=True,
        null=True,
        verbose_name="ITE Land Use Code",
        help_text="ITE Trip Generation manual land use code.",
    )
    trip_rate_override = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Trip rate override (trips/unit)",
    )
    pass_by_trip_pct = models.FloatField(
        blank=True,
        default=0.0,
        verbose_name="Pass-by trip (%)",
        help_text="Percent of trips that are pass-by (diverted from passing traffic).",
    )

    # Meta
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Building Type"

    def __str__(self) -> str:
        return self.name


class PlaceType(models.Model):
    """A place typology that defines right-of-way and street context parameters."""

    # Identity
    name = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True, default="")

    # Right-of-way
    row_allocation_pct = models.FloatField(
        default=25.0,
        verbose_name="ROW allocation (%)",
        help_text="Percent of parcel area dedicated to right-of-way.",
    )

    # Street context
    block_size = models.FloatField(
        blank=True,
        null=True,
        verbose_name="Block size (m)",
        help_text="Average block length in meters.",
    )
    street_pattern = models.CharField(
        max_length=32,
        choices=StreetPatternChoices,
        blank=True,
        default="",
        verbose_name="Street pattern",
    )

    # Meta
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Place Type"

    def __str__(self) -> str:
        return self.name


class PlaceTypeBuildingTypeMix(models.Model):
    """Association between a PlaceType and a BuildingType with a percentage."""

    place_type = models.ForeignKey(
        PlaceType,
        on_delete=models.CASCADE,
        related_name="building_type_mixes",
    )
    building_type = models.ForeignKey(
        BuildingType,
        on_delete=models.CASCADE,
        related_name="place_type_mixes",
    )
    percentage = models.FloatField(
        verbose_name="Mix percentage",
        help_text="Percent of developable area allocated to this building type.",
    )

    class Meta:
        ordering = ("place_type", "building_type")
        verbose_name = "Place Type - Building Type Mix"
        verbose_name_plural = "Place Type - Building Type Mixes"
        constraints = [
            models.UniqueConstraint(
                fields=("place_type", "building_type"),
                name="uq_place_type_building_type",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.place_type.name} → {self.building_type.name} ({self.percentage}%)"
        )

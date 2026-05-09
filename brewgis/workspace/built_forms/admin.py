"""Admin registration for built forms models."""

from __future__ import annotations

from django.contrib import admin

from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix


class PlaceTypeBuildingTypeMixInline(admin.TabularInline):
    """Inline for editing building type mixes within a PlaceType."""

    model = PlaceTypeBuildingTypeMix
    extra = 1
    autocomplete_fields = ("building_type",)


@admin.register(BuildingType)
class BuildingTypeAdmin(admin.ModelAdmin):
    """Admin for BuildingType."""

    list_display = ("name", "du_per_acre", "emp_per_acre", "far", "vintage")
    list_filter = ("vintage",)
    search_fields = ("name", "description")
    fieldsets = (
        ("Identity", {"fields": ("name", "description")}),
        ("Density", {"fields": ("du_per_acre", "emp_per_acre", "far")}),
        (
            "Housing / Household",
            {
                "fields": (
                    "household_size",
                    "tenure_owner_pct",
                    "tenure_renter_pct",
                    "vacancy_rate",
                )
            },
        ),
        (
            "Physical Form",
            {"fields": ("stories", "footprint_per_unit", "building_coverage")},
        ),
        ("Employment", {"fields": ("jobs_by_sector",)}),
        (
            "Water",
            {
                "fields": (
                    "indoor_water_rate",
                    "outdoor_water_rate",
                    "irrigable_area_fraction",
                )
            },
        ),
        ("Energy", {"fields": ("electricity_eui", "gas_eui", "vintage")}),
        (
            "Parking",
            {
                "fields": (
                    "parking_spaces_per_unit",
                    "parking_spaces_per_1000sqft",
                    "parking_sqft_per_space",
                )
            },
        ),
        (
            "Trip Generation",
            {"fields": ("ite_land_use_code", "trip_rate_override", "pass_by_trip_pct")},
        ),
    )


@admin.register(PlaceType)
class PlaceTypeAdmin(admin.ModelAdmin):
    """Admin for PlaceType with inline mix editing."""

    list_display = ("name", "row_allocation_pct", "street_pattern")
    list_filter = ("street_pattern",)
    search_fields = ("name", "description")
    inlines = [PlaceTypeBuildingTypeMixInline]


@admin.register(PlaceTypeBuildingTypeMix)
class PlaceTypeBuildingTypeMixAdmin(admin.ModelAdmin):
    """Admin for PlaceTypeBuildingTypeMix."""

    list_display = ("place_type", "building_type", "percentage")
    list_filter = ("place_type", "building_type")
    autocomplete_fields = ("place_type", "building_type")

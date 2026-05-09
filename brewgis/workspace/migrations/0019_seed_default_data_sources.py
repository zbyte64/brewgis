"""Seed default DataSourceCategory and DataSource records."""

from __future__ import annotations

from django.db import migrations


def seed_catalog(apps, schema_editor) -> None:  # noqa: ANN001, ARG001
    DataSourceCategory = apps.get_model("workspace", "DataSourceCategory")
    DataSource = apps.get_model("workspace", "DataSource")

    # Clear any previously seeded data (from 0018 or elsewhere)
    DataSource.objects.all().delete()
    DataSourceCategory.objects.all().delete()

    # ── Categories ──────────────────────────────────────────────────

    census = DataSourceCategory.objects.create(
        name="Census Data",
        slug="census-data",
        sort_order=1,
    )
    poi = DataSourceCategory.objects.create(
        name="Points of Interest",
        slug="points-of-interest",
        sort_order=2,
    )
    env = DataSourceCategory.objects.create(
        name="Environmental Constraints",
        slug="environmental-constraints",
        sort_order=3,
    )
    parcel = DataSourceCategory.objects.create(
        name="Parcel Data",
        slug="parcel-data",
        sort_order=4,
    )
    boundaries = DataSourceCategory.objects.create(
        name="Boundary Data",
        slug="boundary-data",
        sort_order=5,
    )

    # ── Data Sources ────────────────────────────────────────────────

    sources = [
        # -- Census Data --
        DataSource(
            category=census,
            name="Census ACS",
            slug="census-acs",
            provider="US Census Bureau",
            acquisition_priority="p0",
            is_importable=True,
            data_format="api",
            update_frequency="annual",
            description="Demographics by census tract",
        ),
        DataSource(
            category=census,
            name="LEHD Employment",
            slug="lehd-employment",
            provider="US Census Bureau (LEHD)",
            acquisition_priority="p0",
            is_importable=True,
            data_format="api",
            update_frequency="annual",
            description="Jobs by block",
        ),
        # -- Points of Interest --
        DataSource(
            category=poi,
            name="OSM Points of Interest",
            slug="osm-points-of-interest",
            provider="OpenStreetMap",
            acquisition_priority="p1",
            is_importable=True,
            data_format="api",
            update_frequency="quarterly",
            description="Amenities",
        ),
        # -- Environmental Constraints --
        DataSource(
            category=env,
            name="Floodplains",
            slug="floodplains",
            provider="FEMA",
            acquisition_priority="p0",
            is_importable=False,
            data_format="raster",
            description="Flood/wetland/slope",
        ),
        DataSource(
            category=env,
            name="Wetlands",
            slug="wetlands",
            provider="USFWS",
            acquisition_priority="p0",
            is_importable=False,
            data_format="vector",
            description="Wetland areas",
        ),
        DataSource(
            category=env,
            name="Steep Slopes",
            slug="steep-slopes",
            provider="USGS",
            acquisition_priority="p1",
            is_importable=False,
            data_format="raster",
            description="Slopes > 15%",
        ),
        # -- Parcel Data --
        DataSource(
            category=parcel,
            name="Parcel Fabric",
            slug="parcel-fabric",
            provider="Uploaded by user",
            acquisition_priority="p0",
            is_importable=True,
            data_format="shapefile",
            description="User uploaded parcel data",
        ),
        # -- Boundary Data --
        DataSource(
            category=boundaries,
            name="County Boundary",
            slug="county-boundary",
            provider="US Census Bureau (TIGER)",
            acquisition_priority="p0",
            is_importable=False,
            data_format="vector",
            description="Census TIGER boundary",
        ),
    ]

    DataSource.objects.bulk_create(sources)


def clear_catalog(apps, schema_editor) -> None:  # noqa: ANN001, ARG001
    DataSource = apps.get_model("workspace", "DataSource")
    DataSourceCategory = apps.get_model("workspace", "DataSourceCategory")

    DataSource.objects.filter(
        slug__in=[
            "census-acs",
            "lehd-employment",
            "osm-points-of-interest",
            "floodplains",
            "wetlands",
            "steep-slopes",
            "parcel-fabric",
            "county-boundary",
        ]
    ).delete()
    DataSourceCategory.objects.filter(
        slug__in=[
            "census-data",
            "points-of-interest",
            "environmental-constraints",
            "parcel-data",
            "boundary-data",
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0018_seed_data_catalog"),
    ]

    operations = [
        migrations.RunPython(seed_catalog, clear_catalog),
    ]

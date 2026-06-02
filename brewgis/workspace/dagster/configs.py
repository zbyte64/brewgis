"""Dagster config classes for Brew GIS data pipeline assets.

Separated into this module because ``from __future__ import annotations``
interferes with Dagster's config type resolution in asset files.
"""
# NOTE: No `from __future__ import annotations` here — Dagster 1.13.1
# requires runtime-evaluable type annotations for Config subclass fields.

from dagster import Config


class BaseCanvasETLConfig(Config):
    """Config for the ``base_canvas_etl`` asset.

    Controls the source of parcel data for the SQL-native pipeline.
    External data sources (Census ACS, LEHD) are expected in their
    staging schemas before this asset runs.
    """

    source_table: str = ""
    """PostGIS table to read parcels from (schema.table)."""
    source_geojson: str = ""
    """GeoJSON file path to read parcels from."""
    synthetic_n: int = 0
    """Number of synthetic parcels to generate (for testing)."""
    skip_imputation: bool = False
    """Skip the imputation pass (leave NULLs as-is)."""
    truncate: bool = False
    """Truncate existing data before inserting."""
    target_table: str = "public.base_canvas"
    """Target table for ETL output (schema.table)."""


class OnboardGeographyConfig(Config):
    """Config for the ``onboard_geography`` asset.

    Controls the geography name and parcel source.
    """

    name: str
    """Human-readable name for the geography."""
    parcels_path: str
    """Path to GeoJSON file containing parcel geometries."""
    skip_imputation: bool = False
    """Skip the imputation pass (leave NULLs as-is)."""
    truncate: bool = False
    """Truncate existing base canvas data before inserting."""


class FresnoDemoDataConfig(Config):
    """Config for the ``fresno_demo_data`` asset.

    Controls which dataset(s) to download and whether to force re-download.
    """

    dataset: str = ""
    """Specific dataset key to download (e.g. ``"parcels"``), or ``""`` for all."""
    force_download: bool = False
    """Re-download even if cached file exists."""
    cache_dir: str = ""
    """Directory to store cached files. Empty = default Fresno cache dir."""


class FresnoConstraintsConfig(Config):
    """Config for the ``fresno_constraints`` asset.

    Controls which constraint layers to ingest and their target schema.
    """

    cache_dir: str = ""
    """Path to the Fresno demo cache directory. If empty, uses default."""
    target_schema: str = "fresno_demo"
    """Target database schema for constraint tables."""


class AssignBuiltFormsConfig(Config):
    """Config for the ``assign_built_forms`` asset."""

    db_schema: str = "fresno_demo"
    """Database schema containing the parcels table."""
    table: str = "fresno_parcels"
    """Table name for classified parcels."""


class CreateFresnoScenarioConfig(Config):
    """Config for the ``create_fresno_scenario`` asset."""

    workspace_name: str = "Fresno Demo"
    """Name of the workspace."""
    workspace_schema: str = "fresno_demo"
    """DB schema for the workspace."""
    slug: str = "fresno_baseline"
    """Slug for the scenario."""
    name: str = "Fresno Baseline"
    """Display name for the scenario."""
    base_year: int = 2022
    """Base year for the scenario."""
    horizon_year: int = 2050
    """Horizon year for the scenario."""


class SacogLoadParcelsConfig(Config):
    """Config for the ``sacog_load_parcels`` asset.

    Controls caching and parcel limit for reference parcel loading.
    """

    limit: int = 0
    """Limit parcel count for fast test runs (0 = all)."""
    cache_dir: str = ""
    """Directory to store cached GeoJSON. Empty = default planning/ cache dir."""

class ImputeAreaProportionalConfig(Config):
    """Config for the ``impute_area_proportional_asset``."""

    source_schema: str
    """Schema containing the source table."""
    source_table: str
    """Source table with values to allocate."""
    source_column: str
    """Numeric column on source to use for filling."""
    target_schema: str
    """Schema containing the target table."""
    target_table: str
    """Target table with missing values to fill."""
    target_column: str
    """Column to fill with imputed values."""
    source_geom_col: str = "geom"
    """Geometry column on source table."""
    target_geom_col: str = "geom"
    """Geometry column on target table."""
    scenario_id: str
    """Unique identifier for this run, used in the view alias."""

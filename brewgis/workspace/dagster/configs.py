"""Dagster config classes for Brew GIS data pipeline assets.

Separated into this module because ``from __future__ import annotations``
interferes with Dagster's config type resolution in asset files.
"""
# NOTE: No `from __future__ import annotations` here — Dagster 1.13.1
# requires runtime-evaluable type annotations for Config subclass fields.

from dagster import Config


class BaseCanvasETLConfig(Config):
    """Config for the ``base_canvas_etl`` asset.

    Controls the source of parcel data and which adapters to enable.
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
    fetch_census: bool = False
    """Fetch real Census ACS demographic data."""
    fetch_lehd: bool = False
    """Fetch real LEHD WAC employment data."""
    state_fips: str = ""
    """Two-digit state FIPS code (required with fetch_census/fetch_lehd)."""
    county_fips: str = ""
    """Three-digit county FIPS code (required with fetch_census/fetch_lehd)."""
    target_table: str = "public.base_canvas"
    """Target table for ETL output (schema.table)."""


class OnboardGeographyConfig(Config):
    """Config for the ``onboard_geography`` asset.

    Controls the geography name, parcel source, and which data sources to skip.
    """

    name: str
    """Human-readable name for the geography."""
    parcels_path: str
    """Path to GeoJSON file containing parcel geometries."""
    state_fips: str
    """Two-digit state FIPS code."""
    county_fips: str
    """Three-digit county FIPS code."""
    skip_census: bool = False
    """Skip Census ACS data fetching."""
    skip_lehd: bool = False
    """Skip LEHD WAC data fetching."""
    skip_nlcd: bool = False
    """Skip NLCD land cover classification."""
    skip_osm: bool = False
    """Skip OSM intersection density computation."""
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


class SacogComparisonConfig(Config):
    """Config for the ``sacog_comparison`` asset.

    Controls data sources, parcel limit, and which adapters to enable.
    """

    quick: bool = False
    """Skip NLCD/OSM (use default null sources); only Census + LEHD."""
    limit: int = 0
    """Limit parcel count for fast test runs (0 = all)."""
    skip_census: bool = False
    """Skip Census ACS demographic fetching."""
    skip_lehd: bool = False
    """Skip LEHD employment fetching."""
    truncate: bool = False
    """Truncate existing base_canvas before inserting."""

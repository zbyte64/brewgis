"""SQLMesh configuration for BrewGIS.

Reads ``DATABASE_URL`` from the environment (Django-compatible).
State is stored in a separate ``sqlmesh_state`` schema on the same PostGIS instance.

Monkey-patches
-------------
- ``EngineAdapter.drop_data_object`` — falls back to the opposite object kind
  when DuckDB's postgres_scanner misidentifies a view as a table (or vice versa)
  and retries with CASCADE when dependent objects block the plain DROP.
- ``DuckDBEngineAdapter._create_table`` — when ``replace=True``, explicitly
  drops with CASCADE first to avoid DuckDB's internal DROP+CREATE translation
  failing on PostgreSQL due to dependent views.
"""

from __future__ import annotations

import logging as _logging
import os
import threading
from urllib.parse import urlparse

import sqlglot.expressions as _exp
from sqlmesh.core.config import Config
from sqlmesh.core.config import GatewayConfig
from sqlmesh.core.config import LinterConfig
from sqlmesh.core.config import ModelDefaultsConfig
from sqlmesh.core.config import PostgresConnectionConfig
from sqlmesh.core.config.connection import DuckDBAttachOptions
from sqlmesh.core.config.connection import DuckDBConnectionConfig

_logger = _logging.getLogger(__name__)
_drop_data_object_orig = None
_create_table_orig = None
_singleton_get_orig = None
_singleton_get_cursor_orig = None

# Read-only mode flag — set SQLMESH_DUCKDB_READONLY=1 in the environment
# before any SQLMesh import to enable thread-local read-only DuckDB connections
# (used by the MCP server's SSE transport for concurrent tool access).
_READONLY_MODE = os.environ.get("SQLMESH_DUCKDB_READONLY", "") == "1"
_readonly_pool: DuckDBReadOnlyPool | None = None
# Import is lazy inside _get_readonly_pool() to avoid Django settings cascade


_DUCKDB_PATH = os.environ.get(
    "SQLMESH_DUCKDB_PATH",
    "/app/planning/duckdb_cache.db",
)
_DUCKDB_TMP = os.environ.get(
    "SQLMESH_DUCKDB_TMP",
    "/app/planning/duckdb_tmp",
)


def _get_readonly_pool() -> DuckDBReadOnlyPool:
    """Lazy-initialised singleton for the read-only DuckDB pool."""
    global _readonly_pool
    if _readonly_pool is None:
        from brewgis.workspace.services.duckdb_pool import DuckDBReadOnlyPool

        _readonly_pool = DuckDBReadOnlyPool(_DUCKDB_PATH)
    return _readonly_pool


def _drop_data_object_patched(self, data_object, ignore_if_not_exists=True):
    try:
        return _drop_data_object_orig(self, data_object, ignore_if_not_exists)
    except Exception:
        pass

    # Retry with CASCADE — dependent objects (e.g. views created by comparison
    # models) prevent the plain DROP and PostgreSQL requires explicit CASCADE.
    try:
        if data_object.type.is_table:
            self.drop_table(
                data_object.to_table(),
                exists=ignore_if_not_exists,
                cascade=True,
            )
            _logger.warning(
                "drop_data_object: DROP TABLE CASCADE for %s (had dependents)",
                data_object.to_table().sql(dialect=self.dialect),
            )
            return None
        if data_object.type.is_view:
            self.drop_view(
                data_object.to_table(),
                ignore_if_not_exists=ignore_if_not_exists,
                cascade=True,
            )
            _logger.warning(
                "drop_data_object: DROP VIEW CASCADE for %s (had dependents)",
                data_object.to_table().sql(dialect=self.dialect),
            )
            return None
    except Exception:
        pass

    # Type-swap fallback — DuckDB postgres_scanner sometimes reports PostgreSQL
    # views as BASE TABLE.  If the cascade retry also failed, try the opposite
    # kind before giving up.
    if data_object.type.is_table:
        try:
            self.drop_view(
                data_object.to_table(),
                ignore_if_not_exists=ignore_if_not_exists,
            )
            _logger.warning(
                "drop_data_object: fell back DROP TABLE→DROP VIEW for %s",
                data_object.to_table().sql(dialect=self.dialect),
            )
            return None
        except Exception:
            pass
    elif data_object.type.is_view:
        try:
            self.drop_table(data_object.to_table(), exists=ignore_if_not_exists)
            _logger.warning(
                "drop_data_object: fell back DROP VIEW→DROP TABLE for %s",
                data_object.to_table().sql(dialect=self.dialect),
            )
            return None
        except Exception:
            pass
    raise


def _create_table_patched(
    self,
    table_name_or_schema,
    expression,
    exists=True,
    replace=False,
    target_columns_to_types=None,
    table_description=None,
    column_descriptions=None,
    table_kind=None,
    track_rows_processed=True,
    **kwargs,
):
    if replace:
        # DuckDB's CREATE OR REPLACE TABLE translates internally to
        # DROP+CREATE when talking to PostgreSQL via postgres_scanner.
        # The DROP is sent *without* CASCADE, so PostgreSQL rejects it
        # when other objects (e.g. comparison views) depend on the table.
        #
        # Fix: explicitly DROP ... CASCADE first, then create without
        # replace — the explicit CASCADE goes to PostgreSQL directly.
        table_name = (
            table_name_or_schema.this
            if isinstance(table_name_or_schema, _exp.Schema)
            else table_name_or_schema
        )
        self.drop_table(table_name, exists=True, cascade=True)
        replace = False

    return _create_table_orig(
        self,
        table_name_or_schema,
        expression,
        exists,
        replace,
        target_columns_to_types,
        table_description,
        column_descriptions,
        table_kind,
        track_rows_processed=track_rows_processed,
        **kwargs,
    )


def _singleton_pool_get(self):
    if _READONLY_MODE:
        return _get_readonly_pool().get_connection()
    if not hasattr(self, "_brewgis_lock"):
        object.__setattr__(self, "_brewgis_lock", threading.RLock())
    with self._brewgis_lock:
        return _singleton_get_orig(self)


def _singleton_pool_get_cursor(self):
    if _READONLY_MODE:
        return _get_readonly_pool().get_connection().cursor()
    if not hasattr(self, "_brewgis_lock"):
        object.__setattr__(self, "_brewgis_lock", threading.RLock())
    with self._brewgis_lock:
        return _singleton_get_cursor_orig(self)


def _install_monkeypatch():
    global _drop_data_object_orig, _create_table_orig
    global _singleton_get_orig, _singleton_get_cursor_orig
    from sqlmesh.core.engine_adapter.base import EngineAdapter
    from sqlmesh.core.engine_adapter.duckdb import DuckDBEngineAdapter

    _drop_data_object_orig = EngineAdapter.drop_data_object
    EngineAdapter.drop_data_object = _drop_data_object_patched

    _create_table_orig = DuckDBEngineAdapter._create_table
    DuckDBEngineAdapter._create_table = _create_table_patched

    from sqlmesh.utils.connection_pool import SingletonConnectionPool

    _singleton_get_orig = SingletonConnectionPool.get
    _singleton_get_cursor_orig = SingletonConnectionPool.get_cursor
    SingletonConnectionPool.get = _singleton_pool_get
    SingletonConnectionPool.get_cursor = _singleton_pool_get_cursor

    _logger.debug(
        "EngineAdapter.drop_data_object monkey-patched"
        " (duckdb-postgres#269 workaround + cascade)"
    )
    _logger.debug(
        "SingletonConnectionPool.get/get_cursor monkey-patched (thread-safety)"
    )


_install_monkeypatch()


def _parse_database_url(url: str) -> dict[str, str | int]:
    """Parse a DATABASE_URL into PostgresConnectionConfig kwargs."""
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "postgres",
        "port": parsed.port or 5432,
        "user": parsed.username or "brewgis",
        "password": parsed.password or "brewgis",
        "database": parsed.path.lstrip("/") or "brewgis",
    }


_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgres://brewgis:brewgis@postgres:5432/brewgis",
)

_db_kwargs = _parse_database_url(_DATABASE_URL)

# Postgres connection string for DuckDB postgres_scanner attach
_pg_attach_path = (
    f"dbname={_db_kwargs['database']} "
    f"user={_db_kwargs['user']} "
    f"host={_db_kwargs['host']} "
    f"port={_db_kwargs['port']} "
    f"password={_db_kwargs['password']}"
)


def config_factory(**variables):
    return Config(
        project="brewgis",
        default_gateway="postgis",
        gateways={
            "postgis": GatewayConfig(
                connection=PostgresConnectionConfig(concurrent_tasks=8, **_db_kwargs),
                state_connection=PostgresConnectionConfig(**_db_kwargs),
                state_schema="sqlmesh_state",
                test_connection=PostgresConnectionConfig(**_db_kwargs),
            ),
            "duckdb": GatewayConfig(
                connection=DuckDBConnectionConfig(
                    catalogs={
                        "duckdb": _DUCKDB_PATH,
                        "brewgis": DuckDBAttachOptions(
                            type="postgres",
                            path=_pg_attach_path,
                        ),
                    },
                    extensions=["httpfs", "spatial", "postgres_scanner"],
                    connector_config={
                        "temp_directory": _DUCKDB_TMP,
                    },
                    secrets=[
                        {
                            "type": "s3",
                            "provider": "config",
                            "region": "us-west-2",
                            "endpoint": "s3.us-west-2.amazonaws.com",
                            "url_style": "path",
                        },
                    ],
                ),
            ),
        },
        disable_anonymized_analytics=True,
        model_defaults=ModelDefaultsConfig(
            dialect="postgres",
            start="2024-01-01",
        ),
        linter=LinterConfig(
            enabled=True,
            rules=[
                "invalidselectstarexpansion",
                "NoTransformInJoinWhere",
                "noselectstar",
                "DuckDBGeometryUsage",
            ],
            warn_rules=[
                "MissingKeyIndex",
                "PostStatementIndexTarget",
                "MissingGeometryIndex",
                "UnindexedJoin",
                "UnindexedGroupBy",
                "UnindexedWhereClause",
                "CrossJoinLikeJoin",
                "UnfilteredTableScan",
                "StaticComplexityScore",
                "IndexColumnExistence",
                "AuditColumnExistence",
                "ambiguousorinvalidcolumn",
                # "nomissingaudits",
                "nomissingexternalmodels",
                # "nomissingunittest",
                "DuckDBTransformWarning",
                "DegradingSRIDCast",
            ],
        ),
        variables={
            # Year and vintage parameters for staging models
            "lodes_year": 2008,
            "acs_year": 2013,
            "state_fips": "06",
            "county_fips": "067",
            "tiger_vintage": "2023",
            "tiger_block_vintage": "2020",
            "tiger_bg_vintage": "2013",
            "local_srid": 3310,
            "min_sqft_per_unit": 400,
            "wm_srid": 3857,
            "default_srid": 4326,
            # Scenario table references (overridden per scenario)
            "scenario_schema": "public",
            "base_canvas_table": "base_canvas",
            "parcel_table": "public.parcels",
            "constraint_table": "public.constraints",
            "built_form_table": "public.built_forms",
            "constraints": [],
            # OSM intersection density table (empty = disabled, overridden per-caller)
            "osm_intersection_table": "",
            # Overture release tag for land cover/use themes
            "overture_release_tag": "2026-05-20.0",
            "overture_land_cover_parquet_glob": (
                "s3://overturemaps-us-west-2/release/2026-05-20.0/"
                "theme=base/type=land_cover/*.parquet"
            ),
            "overture_land_use_parquet_glob": (
                "s3://overturemaps-us-west-2/release/2026-05-20.0/"
                "theme=base/type=land_use/*.parquet"
            ),
            # VIDA + Overture building footprint pipeline variables
            "vida_parquet_glob": (
                "s3://us-west-2.opendata.source.coop/vida/"
                "google-microsoft-osm-open-buildings/geoparquet/"
                "by_country_s2/country_iso=USA/*.parquet"
            ),
            "overture_parquet_glob": (
                "s3://overturemaps-us-west-2/release/2026-05-20.0/"
                "theme=buildings/type=building/*.parquet"
            ),
            # Overture Transportation — road segments (used by overture road impervious)
            "overture_transport_parquet_glob": (
                "s3://overturemaps-us-west-2/release/2026-05-20.0/"
                "theme=transportation/type=segment/*.parquet"
            ),
            # ---- CBP County Employment Scaling (wac_block.sql) ----
            # Set to actual CBP 2008 county-level totals for accurate scaling.
            # All default to 0.0 (passthrough — no scaling applied).
            # Source: Census County Business Patterns, 2008 vintage
            #   https://www.census.gov/programs-surveys/cbp.html
            "cbp_county_emp_agriculture": 0.0,
            "cbp_county_emp_extraction": 0.0,
            "cbp_county_emp_construction": 0.0,
            "cbp_county_emp_manufacturing": 0.0,
            "cbp_county_emp_transport_warehousing": 0.0,
            "cbp_county_emp_utilities": 0.0,
            "cbp_county_emp_wholesale": 0.0,
            "cbp_county_emp_retail_services": 0.0,
            "cbp_county_emp_restaurant": 0.0,
            "cbp_county_emp_accommodation": 0.0,
            "cbp_county_emp_arts_entertainment": 0.0,
            "cbp_county_emp_other_services": 0.0,
            "cbp_county_emp_office_services": 0.0,
            "cbp_county_emp_medical_services": 0.0,
            "cbp_county_emp_education": 0.0,
            "cbp_county_emp_public_admin": 0.0,
            "cbp_county_emp_military": 0.0,
            "cbp_preserve_fraction": 0.5,
            # ---- CBP NAICS CNS sub-sector proportions (wac_block_raw.sql) ----
            "cbp_11": 0.0,  # NAICS 11 (ag) share of CNS01
            "cbp_21": 0.0,  # NAICS 21 (extraction) share of CNS01
            "cbp_48": 0.0,  # NAICS 48 (transport) share of CNS03
            "cbp_49": 0.0,  # NAICS 49 (warehousing) share of CNS03
            "cbp_22": 0.0,  # NAICS 22 (utilities) share of CNS03
            "cbp_42": 0.0,  # NAICS 42 (wholesale) share of CNS03
            "cbp_721": 0.0,  # NAICS 721 (accommodation) share of CNS13
            # Overture Sacramento County bbox
            "overture_bbox_min_x": -121.87,
            "overture_bbox_max_x": -121.01,
            "overture_bbox_min_y": 38.02,
            "overture_bbox_max_y": 38.74,
            # Fiscal
            "res_assessed_value_per_du": 350000,
            "nonres_assessed_value_per_sqft": 150,
            "cost_per_du": 5000,
            "cost_per_capita": 2000,
            "cost_per_employee": 1500,
            "property_tax_rate": 1.0,
            "retail_employment_share": 15,
            "sales_per_employee": 100000,
            "sales_tax_rate": 1.0,
            # Development
            "dev_pct": 100,
            "gross_net_pct": 85,
            "density_pct": 100,
            # Transportation
            "transport_nonres_trip_rate": 42.94,
            "transport_pass_by_pct": 0.0,
            "transport_hbw_pct": 0.18,
            "transport_hbo_pct": 0.42,
            "transport_nhb_pct": 0.40,
            "transport_circuity_factor": 1.2,
            "transport_ghg_co2_per_mile": 0.411,
            "transport_ghg_speed_adjust": False,
            "transport_intrazonal_friction": 0.15,
            "transport_study_area_geometry": "",
            "transport_km_to_mi": 0.621371,
            # GHG
            "ghg_egrid_co2_per_kwh": 0.417,
            "ghg_gas_co2_per_kwh": 0.181,
            "ghg_water_supply_kwh_per_mg": 1427,
            "ghg_wastewater_kwh_per_mg": 1911,
            "ghg_liters_per_million_gallons": 3785411.78,
            # Health
            "health_walk_met": 3.5,
            "health_bike_met": 6.0,
            "health_walk_speed_kmh": 4.8,
            "health_bike_speed_kmh": 16.0,
            "health_heat_mortality_reduction_pct": 8.0,
            "health_heat_baseline_met_hours_per_week": 11.25,
            "health_pm25_intake_fraction": 1.6e-6,
            "health_pm25_concentration_response": 0.0062,
            "health_background_dalys_per_capita": 0.013,
            "health_background_death_rate": 0.008,
            "health_weeks_per_year": 52,
            # Land Consumption / Parking
            "parking_per_unit": 0.5,
            "parking_per_employee": 0.2,
            "ground_coverage_factor": 0.6,
            "parking_space_sqft": 300,
            "row_fraction": 0.15,
            # Stormwater
            "stormwater_annual_precipitation_in": 12.0,
            # Tree Canopy
            "tree_canopy_baseline_temp": 95.0,
            "tree_canopy_temp_per_10pct": 1.0,
            # VMT Mitigation
            "vmt_fee_rate_dollars_per_vmt": 295.0,
            "vmt_exempt_pct": 0.0,
            # Cost of Sprawl
            "sprawl_infrastructure_cost_per_du": 15000,
            "sprawl_capital_cost_per_du": 50000,
            # Agriculture
            "crop_yield_per_acre": 8.0,
            "crop_market_price_per_ton": 200,
            "crop_production_cost_per_acre": 800,
            "crop_water_per_acre_af": 3.0,
            "crop_labor_hours_per_acre": 15,
            "crop_truck_trips_per_acre": 2,
            # Housing / Displacement
            "housing_cost_burden_rate": 0.30,
            "housing_severe_burden_rate": 0.50,
            "displacement_income_threshold": 50000,
            "displacement_minority_threshold": 0.50,
            "displacement_rent_burden_threshold": 0.30,
            "displacement_college_education_threshold": 0.25,
            # Built form defaults
            "res_far_default": 0.5,
            "nonres_indoor_water_rate": 0.0,
            # KNN test isolation variables (overridden in test environments)
            "parcel_known_features_model": "brewgis.assessor.parcel_known_features",
            "parcel_partition_stats_model": "brewgis.assessor.parcel_partition_stats",
            **variables,
        },
        gateway_managed_virtual_layer=True,
    )


config = config_factory()

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
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import sqlglot.expressions as _exp
from sqlmesh.core.config import Config
from sqlmesh.core.config import GatewayConfig
from sqlmesh.core.config import LinterConfig
from sqlmesh.core.config import ModelDefaultsConfig
from sqlmesh.core.config import PostgresConnectionConfig
from sqlmesh.core.config.connection import DuckDBAttachOptions
from sqlmesh.core.config.connection import DuckDBConnectionConfig

if TYPE_CHECKING:
    from brewgis.workspace.services.duckdb_pool import DuckDBReadOnlyPool

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
                "drop_data_object: DROP TABLE for %s (had dependents)",
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
                "drop_data_object: DROP VIEW for %s (had dependents)",
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
    return

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


def config_factory(*, cache_dir: str | None = None, **variables):
    return Config(
        project="brewgis",
        default_gateway="postgis",
        # SQLMesh's on-disk cache of rendered model definitions/queries. Defaults
        # to ``<project>/.cache``; a caller passes its own directory when it must
        # not inherit that cache — the analysis models' blueprints are derived
        # from database rows, which the cache cannot see (see
        # ``workspace/analysis/pipeline.run_modules_sync``).
        cache_dir=cache_dir,
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
                    extensions=[
                        "httpfs",
                        "spatial",
                        "postgres_scanner",
                        "cache_httpfs",
                        "zipfs",
                        "raster",
                    ],
                    connector_config={
                        "temp_directory": _DUCKDB_TMP,
                        # cache_httpfs on-disk block cache. NO force_download:
                        # it made every s3:// parquet file an upfront full
                        # download (277 GB theme -> never completes).
                        # ArcGIS FeatureServers (FEMA NFHL, CA DOC farmland)
                        # that mishandle Range requests are covered by
                        # cache_httpfs' default auto_fallback_to_full_download.
                        #
                        # IMPORTANT: the extension must be a CURRENT community
                        # build. The artifact pinned in images built before
                        # ~2026-09 wedged/busy-looped on s3:// parquet reads
                        # (duck-read-cache-fs#331 family); a fresh
                        # `FORCE INSTALL cache_httpfs FROM community` fixed it
                        # (verified 2026-09-08: s3 fetch 149 s + cache writes;
                        # ArcGIS page 11.7 s). Rebuild the django image after
                        # touching preload_duckdb.py.
                        "cache_httpfs_type": "on_disk",
                        "cache_httpfs_cache_directory": "/app/planning/http_cache",
                        "cache_httpfs_evict_policy": "lru_sp",
                        # this is a hazard for census data and other
                        # non-stable responses, must be large. cache_httpfs
                        # caches one entry per (file, start, length) range, so
                        # a response is only cached atomically — never as a mix
                        # of blocks cached before and after it changed — when
                        # its whole body fits in a single block. The value must
                        # be a power of two; the extension rejects anything
                        # else outright ("cache_httpfs_cache_block_size must be
                        # a power of two").
                        # 2^25 (32 MiB) is 4x the largest response this project
                        # fetches — FEMA NFHL page 7.9 MiB, ArcGIS parcel page
                        # 1.9 MiB (both measured 2026-09-19) — while keeping
                        # the ranges requested from object storage at 32 MiB
                        # instead of 128 MiB (under a 128 MiB block the cached
                        # entries were 128 MiB ranges), which is over-fetch for
                        # row-group-pushed parquet reads.
                        "cache_httpfs_cache_block_size": 33554432,
                        "cache_httpfs_min_disk_bytes_for_cache": 1073741824,
                        "allow_asterisks_in_http_paths": True,
                        "httpfs_connection_caching": True,
                        "http_retry_wait_ms": 1000,
                        "unsafe_disable_etag_checks": True,
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
            warn_rules=[
                "invalidselectstarexpansion",
                "NoTransformInJoinWhere",
                "noselectstar",
                "DuckDBGeometryUsage",
                "MissingKeyIndex",
                "PostStatementIndexTarget",
                "SnapshotHashIndexName",
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
            # Census API key (loaded from env; empty string = public data only)
            "census_api_key": os.environ.get("CENSUS_API_KEY", ""),
            # Year and vintage parameters for staging models
            "state_fips": "06",
            "tiger_vintage": "2023",
            "tiger_block_vintage": "2020",
            # Block-group vintage. The ACS and PDB staging models no longer read it:
            # each region pins its own `bg_vintage` blueprint variable (fresno 2023,
            # sacog 2013) because the TIGER block-group vintage has to match the
            # vintage of the release being joined. Kept for the Django services that
            # pass it as a run variable (census_fetcher / lehd_fetcher).
            "tiger_bg_vintage": "2013",
            "local_srid": 3310,
            "min_sqft_per_unit": 400,
            "wm_srid": 3857,
            "default_srid": 4326,
            # Scenario table references (overridden per scenario)
            "scenario_schema": "public",
            "base_canvas_table": "base_canvas",
            # Default parcel adapter (analysis models read @parcel_table as a
            # per-scenario config var — core_end_state). Region chains use the
            # blueprinted parcel_shim instances instead.
            "parcel_table": "brewgis.sacog.parcel_shim",
            "constraint_table": "public.constraints",
            "built_form_table": "public.built_forms",
            "constraints": [],
            # OSM intersection density table (empty = disabled, overridden per-caller)
            "osm_intersection_table": "",
            # Overture release tag for land cover/use themes
            "overture_release_tag": "2026-08-19.0",
            "overture_land_cover_parquet_glob": (
                "s3://overturemaps-us-west-2/release/2026-08-19.0/"
                "theme=base/type=land_cover/*.parquet"
            ),
            "overture_land_use_parquet_glob": (
                "s3://overturemaps-us-west-2/release/2026-08-19.0/"
                "theme=base/type=land_use/*.parquet"
            ),
            # VIDA + Overture building footprint pipeline variables
            "vida_parquet_glob": (
                "s3://us-west-2.opendata.source.coop/vida/"
                "google-microsoft-osm-open-buildings/geoparquet/"
                "by_country_s2/country_iso=USA/*.parquet"
            ),
            "overture_parquet_glob": (
                "s3://overturemaps-us-west-2/release/2026-08-19.0/"
                "theme=buildings/type=building/*.parquet"
            ),
            # Overture Transportation — road segments (used by overture road impervious)
            "overture_transport_parquet_glob": (
                "s3://overturemaps-us-west-2/release/2026-08-19.0/"
                "theme=transportation/type=segment/*.parquet"
            ),
            # ---- NLCD DuckDB raster models ----
            # NLCD land cover and tree canopy year for WCS coverage IDs.
            # nlcd_parcel_source / nlcd_parcel_srid are bound per region by the
            # nlcd_parcel_stats / nlcd_tree_canopy_parcel_stats blueprints
            # (sacog: public.sacog_comparison_parcels @3310; fresno:
            # brewgis.fresno.parcels @4326).
            "nlcd_land_cover_year": 2021,
            "nlcd_tree_canopy_year": 2016,
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
            # Transportation
            # These two are referenced by no model — kept as the last
            # transport-domain config vars. Every param the analysis models
            # *do* read is now baked per scenario into their blueprints (see
            # module_registry.ANALYSIS_PARAMETERS).
            "transport_pass_by_pct": 0.0,
            "transport_km_to_mi": 0.621371,
            **variables,
        },
        gateway_managed_virtual_layer=True,
    )


config = config_factory()

"""SQLMesh configuration for BrewGIS.

Reads ``DATABASE_URL`` from the environment (Django-compatible).
State is stored in a separate ``sqlmesh_state`` schema on the same PostGIS instance.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from sqlmesh.core.config import Config
from sqlmesh.core.config import GatewayConfig
from sqlmesh.core.config import LinterConfig
from sqlmesh.core.config import ModelDefaultsConfig
from sqlmesh.core.config import PostgresConnectionConfig
from sqlmesh.core.config.connection import DuckDBAttachOptions
from sqlmesh.core.config.connection import DuckDBConnectionConfig


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
            ),
            "duckdb": GatewayConfig(
                connection=DuckDBConnectionConfig(
                    catalogs={
                        "duckdb": "/app/planning/duckdb_cache.db",
                        "brewgis": DuckDBAttachOptions(
                            type="postgres",
                            path=_pg_attach_path,
                        ),
                    },
                    extensions=["httpfs", "spatial", "postgres_scanner"],
                    connector_config={
                        "temp_directory": "/app/planning/duckdb_tmp",
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
            ],
            warn_rules=[
                # "MissingGeometryIndex",
                "UnindexedJoin",
                "ambiguousorinvalidcolumn",
                # "nomissingaudits",
                "nomissingexternalmodels",
                # "nomissingunittest",
            ],
        ),
        variables={
            # Year and vintage parameters for staging models
            "lodes_year": 2008,
            "acs_year": 2013,
            "tiger_vintage": "2023",
            "tiger_block_vintage": "2020",
            "tiger_bg_vintage": "2013",
            "local_srid": 3310,
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
            **variables,
        },
        gateway_managed_virtual_layer=True,
    )


config = config_factory()

"""Service-layer Dagster assets for spatial allocation, imputation, and ETL.

These assets wrap the existing service-layer functions (spatial allocator,
stitcher/imputation, canvas ETL) as software-defined assets for orchestration
within Dagster's asset graph.
"""

from typing import Any

from dagster import AssetExecutionContext
from dagster import AssetIn
from dagster import AssetKey

from dagster import MaterializeResult
from dagster import asset

from brewgis.workspace.dagster.resources.postgres_resource import PostgresResource
from brewgis.workspace.dagster.configs import AssignBuiltFormsConfig
from brewgis.workspace.dagster.configs import BaseCanvasETLConfig
from brewgis.workspace.dagster.configs import CreateFresnoScenarioConfig
from brewgis.workspace.dagster.configs import FresnoConstraintsConfig
from brewgis.workspace.dagster.configs import OnboardGeographyConfig
from brewgis.gx import run_checkpoint

# ═══════════════════════════════════════════════════════════════════════
# Assets
# ═══════════════════════════════════════════════════════════════════════


@asset(
    group_name="etl",
    compute_kind="python",
    ins={
        "raw_parcels": AssetIn(key=AssetKey("raw_parcels")),
    },
)
def spatial_allocation(
    context: AssetExecutionContext,
    postgres: PostgresResource,
    raw_parcels: Any,
) -> MaterializeResult:
    """Run the spatial allocator to allocate attributes to parcels.

    Consumes the raw parcels asset (from file upload or base canvas ETL)
    and produces allocated parcel attributes.
    """
    # Placeholder — Phase 2 will wire the actual service
    # from brewgis.workspace.services.spatial_allocator import allocate_attributes
    context.log.info("spatial_allocation asset invoked (not yet wired)")
    # GX gate: validate spatial allocation output
    try:
        gx_result = run_checkpoint("spatial_allocation")
        if not gx_result["success"] and gx_result.get("severity") == "warning":
            context.log.warning(
                "GX warning for spatial_allocation: %s",
                ", ".join(gx_result["failures"][:3]),
            )
    except Exception as exc:
        context.log.warning("GX checkpoint error for spatial_allocation: %s", exc)
    return MaterializeResult(metadata={"status": "placeholder"})


@asset(
    group_name="etl",
    compute_kind="python",
    ins={
        "allocated_parcels": AssetIn(key=AssetKey("spatial_allocation")),
    },
)
def imputation(
    context: AssetExecutionContext,
    postgres: PostgresResource,
    allocated_parcels: Any,
) -> MaterializeResult:
    """Run imputation engine to fill missing attribute values.

    Chains after spatial allocation to apply area-proportional and
    built-form-default imputation strategies.
    """
    context.log.info("imputation asset invoked (not yet wired)")
    # GX gate: validate imputation output
    try:
        gx_result = run_checkpoint("column_stitching")
        if not gx_result["success"] and gx_result.get("severity") == "warning":
            context.log.warning(
                "GX warning for column_stitching: %s",
                ", ".join(gx_result["failures"][:3]),
            )
    except Exception as exc:
        context.log.warning("GX checkpoint error for column_stitching: %s", exc)
    return MaterializeResult(metadata={"status": "placeholder"})


@asset(
    group_name="etl",
    compute_kind="python",
)
def base_canvas_etl(
    context: AssetExecutionContext,
    config: BaseCanvasETLConfig,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """ETL pipeline for base canvas data import and validation.

    Orchestrates reading source data, running the 11-step ETL pipeline,
    and writing to the base canvas staging table.

    Configure via :class:`BaseCanvasETLConfig`:
    - Provide one of ``source_table``, ``source_geojson``, or ``synthetic_n``
    - Optionally enable Census and/or LEHD data fetching with
      ``fetch_census``/``fetch_lehd`` plus ``state_fips``/``county_fips``
    """
    from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL
    from brewgis.workspace.services.calibration_registry import (  # noqa: PLC0415
        NATIONAL_DEFAULT,
    )

    # Build adapters based on config
    demographic_source = None
    if config.fetch_census:
        if not config.state_fips or not config.county_fips:
            raise ValueError("--fetch-census requires state_fips and county_fips")
        from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
            CensusDemographicSource,
        )

        demographic_source = CensusDemographicSource(
            state_fips=config.state_fips,
            county_fips=config.county_fips,
        )

    employment_source = None
    if config.fetch_lehd:
        if not config.state_fips or not config.county_fips:
            raise ValueError("--fetch-lehd requires state_fips and county_fips")
        from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
            LEHDEmploymentSource,
        )

        employment_source = LEHDEmploymentSource(
            state_fips=config.state_fips,
            county_fips=config.county_fips,
        )

    etl = BaseCanvasETL(
        calibration=NATIONAL_DEFAULT,
        demographic_source=demographic_source,
        employment_source=employment_source,
        target_table=config.target_table,
    )

    result = etl.run(
        source_table=config.source_table or None,
        source_geojson=config.source_geojson or None,
        synthetic_n=config.synthetic_n or None,
        skip_imputation=config.skip_imputation,
        truncate=config.truncate,
    )

    if result["status"] == "error":
        raise RuntimeError(result.get("error", "ETL pipeline failed"))

    context.log.info(
        "base_canvas_etl: %s rows in %.1fs",
        result.get("rows", 0),
        result.get("elapsed", 0),
    )
    # GX gate: validate base canvas ETL output
    try:
        gx_result = run_checkpoint("base_canvas_etl")
        if not gx_result["success"] and gx_result.get("severity") == "critical":
            raise RuntimeError(
                "GX gate failed for base_canvas_etl: %s"
                % ", ".join(gx_result["failures"][:5]),
            )
    except RuntimeError:
        raise
    except Exception as exc:
        context.log.warning("GX checkpoint error for base_canvas_etl: %s", exc)

    return MaterializeResult(
        metadata={
            "status": result["status"],
            "rows": result.get("rows", 0),
            "elapsed_s": result.get("elapsed", 0),
        }
    )


@asset(
    group_name="etl",
    compute_kind="python",
)
def onboard_geography(
    context: AssetExecutionContext,
    config: OnboardGeographyConfig,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """Onboard a new geography: build adapters, run ETL, and print summary.

    Creates a base canvas for a new geography by reading parcel geometries
    from a GeoJSON file, optionally fetching Census/LEHD/NLCD/OSM data,
    and running the full ETL pipeline.
    """
    from django.db import connection  # noqa: PLC0415

    demographic_source = None
    employment_source = None
    land_use_source = None
    intersection_density_source = None
    irrigation_source = None

    if not config.skip_census:
        from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
            CensusDemographicSource,
        )

        demographic_source = CensusDemographicSource(
            state_fips=config.state_fips,
            county_fips=config.county_fips,
        )

    if not config.skip_lehd:
        from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
            LEHDEmploymentSource,
        )

        employment_source = LEHDEmploymentSource(
            state_fips=config.state_fips,
            county_fips=config.county_fips,
        )

    if not config.skip_nlcd:
        import geopandas as gpd  # noqa: PLC0415

        try:
            sample_gdf = gpd.read_file(config.parcels_path)
            bbox = (
                float(sample_gdf.total_bounds[0]),
                float(sample_gdf.total_bounds[1]),
                float(sample_gdf.total_bounds[2]),
                float(sample_gdf.total_bounds[3]),
            )
            from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
                NLCDFetcher,
            )

            nlcd_source = NLCDFetcher(bbox=bbox)
            land_use_source = nlcd_source
            irrigation_source = nlcd_source
        except Exception:
            context.log.warning("Could not compute bbox; NLCD/OSM skipped")

    if not config.skip_osm:
        try:
            import geopandas as gpd  # noqa: PLC0415

            sample_gdf = gpd.read_file(config.parcels_path)
            bbox = (
                float(sample_gdf.total_bounds[0]),
                float(sample_gdf.total_bounds[1]),
                float(sample_gdf.total_bounds[2]),
                float(sample_gdf.total_bounds[3]),
            )
            from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
                OSMIntersectionDensitySource,
            )

            intersection_density_source = OSMIntersectionDensitySource(bbox=bbox)
        except Exception:
            context.log.debug("OSM init failed")

    from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL

    etl = BaseCanvasETL(
        demographic_source=demographic_source,
        employment_source=employment_source,
        land_use_source=land_use_source,
        irrigation_source=irrigation_source,
        intersection_density_source=intersection_density_source,
    )

    context.log.info("Running base canvas ETL pipeline...")
    result = etl.run(
        source_geojson=config.parcels_path,
        skip_imputation=config.skip_imputation,
        truncate=config.truncate,
    )

    if result["status"] == "error":
        raise RuntimeError(result.get("error", "Unknown ETL error"))

    context.log.info(
        "onboard_geography: %s rows in %.1fs",
        result.get("rows", 0),
        result.get("elapsed", 0),
    )

    # Print summary
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'base_canvas')"
        )
        if cursor.fetchone()[0]:
            cursor.execute("SELECT COUNT(*) FROM public.base_canvas")
            row_count = cursor.fetchone()[0]
            context.log.info("Total rows in base_canvas: %s", row_count)

    return MaterializeResult(
        metadata={
            "status": result["status"],
            "rows": result.get("rows", 0),
            "elapsed_s": result.get("elapsed", 0),
            "name": config.name,
        }
    )


@asset(
    group_name="etl",
    compute_kind="python",
)
def fresno_constraints(
    context: AssetExecutionContext,
    config: FresnoConstraintsConfig,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """Ingest Fresno constraint layers (flood zones, wetlands, farmland).

    Reads cached GeoJSON files from the Fresno demo cache directory and
    writes them as PostGIS tables in the target schema.
    """
    from pathlib import Path  # noqa: PLC0415

    import geopandas as gpd  # noqa: PLC0415
    from django.db import connection  # noqa: PLC0415

    from brewgis.workspace.services._db import get_engine  # noqa: PLC0415
    from brewgis.workspace.services.fresno_downloader import CACHE_DIR  # noqa: PLC0415

    cache_dir = Path(config.cache_dir) if config.cache_dir else CACHE_DIR
    schema = config.target_schema

    constraint_files = {
        "flood_zones.geojson": "floodplains",
        "wetlands.geojson": "wetlands",
        "farmland.geojson": "farmland",
    }

    ingested: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    # Ensure schema exists
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    for filename, target_table in constraint_files.items():
        filepath = cache_dir / filename
        if not filepath.exists():
            context.log.info(
                "  [SKIP] %s not cached; skipping %s", filename, target_table
            )
            skipped.append(target_table)
            continue

        context.log.info("Ingesting %s -> %s.%s...", filename, schema, target_table)
        try:
            df = gpd.read_file(str(filepath))
            if df.empty:
                context.log.info("  [SKIP] Empty dataset: %s", filename)
                skipped.append(target_table)
                continue
            df.columns = [c.lower() for c in df.columns]
            if "geom" not in df.columns and "geometry" in df.columns:
                df = df.rename_geometry("geom")
            engine = get_engine()
            df.to_postgis(
                target_table,
                engine,
                schema=schema,
                if_exists="replace",
                chunksize=50000,
            )
            ingested.append(target_table)
            context.log.info("  %s: %d features", target_table, len(df))
        except Exception:
            context.log.exception("Failed to ingest %s", filename)
            failed.append(target_table)

    # Create empty steep_slopes table if not exists
    with connection.cursor() as cursor:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS "{schema}".steep_slopes (
                id SERIAL PRIMARY KEY,
                geom geometry(Polygon, 4326)
            )
        """)
    context.log.info("Created empty steep_slopes table (DEM deferred)")

    metadata: dict[str, Any] = {
        "ingested": len(ingested),
        "skipped": len(skipped),
        "failed": len(failed),
        "ingested_tables": ingested,
    }
    return MaterializeResult(metadata=metadata)


@asset(
    group_name="etl",
    compute_kind="python",
)
def assign_built_forms(
    context: AssetExecutionContext,
    config: AssignBuiltFormsConfig,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """Assign built form keys and intersection density via BuiltFormClassifier.

    Reads parcels from the ETL-produced table, runs the heuristic classifier,
    and writes classified data back.
    """
    import geopandas as gpd  # noqa: PLC0415
    from django.db import connection  # noqa: PLC0415

    from brewgis.workspace.services._db import get_engine  # noqa: PLC0415
    from brewgis.workspace.services.built_form_classifier import (  # noqa: PLC0415
        BuiltFormClassifier,
    )

    schema = config.db_schema
    table = config.table

    # Count parcels
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT count(*) FROM "{schema}"."{table}"')
        total = cursor.fetchone()[0]
        context.log.info("Loaded %s parcels for classification", total)

    gdf = gpd.GeoDataFrame.from_postgis(
        f'SELECT * FROM "{schema}"."{table}"',
        connection,
        geom_col="geometry",
    )
    context.log.info("Loaded %s parcels in GeoDataFrame", len(gdf))

    classifier = BuiltFormClassifier(strategy="heuristic")
    gdf = classifier.assign(gdf)

    engine = get_engine()
    gdf.to_postgis(table, engine, schema=schema, if_exists="replace", chunksize=50000)
    context.log.info("Written %s classified parcels back", len(gdf))

    # Report distribution
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT bf.built_form_key, bt.name, COUNT(*) AS cnt\n"
            f"FROM {schema}.{table} bf\n"
            f"LEFT JOIN {schema}.built_forms bt ON bf.built_form_key = bt.id\n"
            f"GROUP BY bf.built_form_key, bt.name\n"
            f"ORDER BY bf.built_form_key"
        )
        rows = cursor.fetchall()
        for key, name, cnt in rows:
            context.log.info(
                "  built_form_key=%s (%s): %s parcels", key, name or f"PK {key}", cnt
            )

    return MaterializeResult(
        metadata={
            "parcels_classified": len(gdf),
            "schema": schema,
            "table": table,
        }
    )


@asset(
    group_name="etl",
    compute_kind="python",
)
def create_fresno_scenario(
    context: AssetExecutionContext,
    config: CreateFresnoScenarioConfig,
    postgres: PostgresResource,  # noqa: ARG001
) -> MaterializeResult:
    """Create the base scenario for the Fresno demo workspace.

    Creates a Scenario model instance linked to a Workspace and sets up
    the dbt variables needed for analysis.
    """
    from django.db import connection as db_conn  # noqa: PLC0415

    from brewgis.workspace.models import Scenario  # noqa: PLC0415
    from brewgis.workspace.models import Workspace  # noqa: PLC0415

    # Ensure schema exists
    with db_conn.cursor() as cursor:
        cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{config.workspace_schema}"')

    workspace, _ = Workspace.objects.get_or_create(
        name=config.workspace_name,
        defaults={"db_schema": config.workspace_schema},
    )
    context.log.info("Workspace: %s (schema: %s)", workspace.name, workspace.db_schema)

    scenario, created = Scenario.objects.get_or_create(
        slug=config.slug,
        workspace=workspace,
        defaults={
            "name": config.name,
            "description": f"{config.name} for Fresno Demo",
            "scenario_type": "base",
            "base_year": config.base_year,
            "horizon_year": config.horizon_year,
        },
    )
    context.log.info(
        "Scenario %s: %s",
        "created" if created else "already exists",
        scenario.name,
    )

    # Create target schema for scenario
    with db_conn.cursor() as cursor:
        cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{scenario.target_schema}"')

    return MaterializeResult(
        metadata={
            "workspace_id": workspace.pk,
            "workspace_name": workspace.name,
            "scenario_id": scenario.pk,
            "scenario_slug": scenario.slug,
            "scenario_type": scenario.scenario_type,
            "target_schema": scenario.target_schema,
            "created": created,
        }
    )

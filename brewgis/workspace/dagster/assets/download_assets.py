"""Dagster assets for downloading and caching external datasets.

Wraps the ``fresno_downloader`` service functions as software-defined
assets for orchestration within Dagster's asset graph.
"""

from pathlib import Path
from typing import Any

from dagster import AssetExecutionContext
from dagster import AssetSpec
from dagster import MaterializeResult
from dagster import asset

from brewgis.workspace.dagster.configs import FresnoDemoDataConfig
from brewgis.workspace.services.fresno_downloader import CACHE_DIR as FRESNO_CACHE_DIR
from brewgis.workspace.services.fresno_downloader import download_all_datasets

# ── Asset specs for individual datasets ──────────────────────────────

fresno_parcels = AssetSpec(key="fresno_parcels", group_name="ingestion")
fresno_city_boundary = AssetSpec(key="fresno_city_boundary", group_name="ingestion")
fresno_flood_zones = AssetSpec(key="fresno_flood_zones", group_name="ingestion")
fresno_farmland = AssetSpec(key="fresno_farmland", group_name="ingestion")
fresno_wetlands = AssetSpec(key="fresno_wetlands", group_name="ingestion")

# ── Assets ───────────────────────────────────────────────────────────


@asset(
    group_name="ingestion",
    compute_kind="python",
    key="fresno_demo_data",
)
def fresno_demo_data(
    context: AssetExecutionContext,
    config: FresnoDemoDataConfig,
) -> MaterializeResult:
    """Download and cache Fresno demo datasets from public sources.

    Produces cached GeoJSON files for parcels, city boundary, flood zones,
    wetlands, and farmland. Downstream assets (constraints, ETL) read from
    the cache directory.
    """
    cache_dir = Path(config.cache_dir) if config.cache_dir else FRESNO_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    dataset_arg: str | None = config.dataset or None

    results = download_all_datasets(
        cache_dir=cache_dir,
        force=config.force_download,
        dataset=dataset_arg,
    )

    downloaded = [r for r in results if r["status"] == "downloaded"]
    cached = [r for r in results if r["status"] == "cached"]
    failed = [r for r in results if r["status"] == "failed"]

    total_size = sum(
        r.get("size", 0) for r in results if r["status"] in ("downloaded", "cached")
    )

    metadata: dict[str, Any] = {
        "downloaded": len(downloaded),
        "cached": len(cached),
        "failed": len(failed),
        "total_size_bytes": total_size,
        "cache_dir": str(cache_dir),
    }
    for r in results:
        metadata[f"status/{r['key']}"] = r["status"]

    context.log.info(
        "fresno_demo_data: %d downloaded, %d cached, %d failed, %s total",
        len(downloaded),
        len(cached),
        len(failed),
        _format_size(total_size) if total_size else "0 B",
    )

    return MaterializeResult(metadata=metadata)


def _format_size(size: int) -> str:
    """Format byte count as human-readable string."""
    one_kb = 1024
    one_mb = one_kb * one_kb
    if size < one_kb:
        return f"{size} B"
    if size < one_mb:
        return f"{size / one_kb:.1f} KB"
    return f"{size / one_mb:.1f} MB"

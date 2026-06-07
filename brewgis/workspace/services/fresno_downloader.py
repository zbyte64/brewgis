"""Download and cache Fresno demo data from public sources.

Extracted from ``download_fresno_demo`` management command for reuse
by callers.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

CACHE_DIR = Path(settings.BASE_DIR) / "planning" / "fresno_demo"

# ── Data source definitions ──────────────────────────────────────────

DATASETS: dict[str, dict[str, Any]] = {
    "parcels": {
        "description": "Fresno County parcel boundaries (Fresno urban area)",
        "source": "Fresno County ArcGIS FeatureServer",
        "base_url": (
            "https://services6.arcgis.com/Gs01XZPFhKUG8tKU/ArcGIS/rest/services"
            "/Fresno_County_Parcels/FeatureServer/0/query"
        ),
        "params": {
            "where": "1=1",
            "outFields": "APN,AGENCY_COD,ROLL_YEAR,SHAPE_AREA",
            "returnGeometry": "true",
            "f": "json",
            "inSR": "4326",
            "outSR": "4326",
            "resultRecordCount": "4000",
            "geometry": '{"xmin":-119.82,"ymin":36.72,"xmax":-119.72,"ymax":36.80}',
            "geometryType": "esriGeometryEnvelope",
        },
        "expected_count": 200_000,
        "filename": "fresno_parcels.geojson",
        "needs_pagination": True,
    },
    "city_boundary": {
        "description": "City of Fresno boundary",
        "source": "City of Fresno GIS Hub",
        "base_url": (
            "https://city-of-fresno-gis-hub-cityoffresno.hub.arcgis.com/api"
            "/download/v1/items/6825e97701754a65af95564d41213e92/geojson"
        ),
        "expected_count": 1,
        "filename": "fresno_city_boundary.geojson",
    },
    "flood_zones": {
        "description": "FEMA NFHL flood zones (Fresno County area)",
        "source": "FEMA National Flood Hazard Layer",
        "base_url": (
            "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL"
            "/MapServer/1/query"
        ),
        "params": {
            "where": "1=1",
            "outFields": "FLD_ZONE,FLD_ZONE,SFHA_TF,STATIC_BFE",
            "returnGeometry": "true",
            "f": "json",
            "inSR": "4326",
            "outSR": "4326",
            "resultRecordCount": "2000",
            "geometry": '{"xmin":-119.82,"ymin":36.72,"xmax":-119.72,"ymax":36.80}',
            "geometryType": "esriGeometryEnvelope",
        },
        "expected_count": 500,
        "filename": "flood_zones.geojson",
        "needs_pagination": True,
    },
}

ADDITIONAL_DATASETS: dict[str, dict[str, Any]] = {
    "farmland": {
        "description": "Important Farmland (Fresno County)",
        "source": "CA Department of Conservation",
        "base_url": (
            "https://gis.conservation.ca.gov/server/rest/services/DLRP"
            "/CaliforniaImportantFarmland_mostrecent/FeatureServer/0/query"
        ),
        "params": {
            "where": "County LIKE '%Fresno%'",
            "outFields": "OBJECTID,County,Code",
            "returnGeometry": "true",
            "f": "json",
            "inSR": "4326",
            "outSR": "4326",
            "resultRecordCount": "2000",
        },
        "expected_count": 10000,
        "filename": "farmland.geojson",
        "needs_pagination": True,
    },
    "wetlands": {
        "description": "Wetlands (Fresno County area)",
        "source": "US Fish & Wildlife Service NWI",
        "base_url": (
            "https://www.fws.gov/wetlands/arcgis/rest/services"
            "/Wetlands/MapServer/0/query"
        ),
        "params": {
            "where": "ATTRIBUTE LIKE '%Fresh%'",
            "outFields": "ATTRIBUTE,WETLAND_TYPE",
            "returnGeometry": "true",
            "f": "json",
            "inSR": "4326",
            "outSR": "4326",
            "resultRecordCount": "2000",
            "geometry": '{"xmin":-119.82,"ymin":36.72,"xmax":-119.72,"ymax":36.80}',
            "geometryType": "esriGeometryEnvelope",
        },
        "expected_count": 500,
        "filename": "wetlands.geojson",
        "needs_pagination": True,
    },
}


def arcgis_to_geojson_feature(arcgis_feature: dict[str, Any]) -> dict[str, Any]:
    """Convert an ArcGIS JSON feature to GeoJSON feature format."""
    props = arcgis_feature.get("attributes", {})
    arc_geom = arcgis_feature.get("geometry")
    geojson_geom: dict[str, Any] | None = None

    if arc_geom:
        if "x" in arc_geom and "y" in arc_geom:
            z = arc_geom.get("z")
            coords = [arc_geom["x"], arc_geom["y"]]
            if z is not None:
                coords.append(z)
            geojson_geom = {"type": "Point", "coordinates": coords}
        elif "rings" in arc_geom:
            geojson_geom = {"type": "Polygon", "coordinates": arc_geom["rings"]}
        elif "paths" in arc_geom:
            paths = arc_geom["paths"]
            geom_type = "MultiLineString" if len(paths) > 1 else "LineString"
            geojson_geom = {
                "type": geom_type,
                "coordinates": paths if geom_type == "MultiLineString" else paths[0],
            }

    return {"type": "Feature", "geometry": geojson_geom, "properties": props}


def build_url(info: dict[str, Any], offset: int = 0) -> str:
    """Build a URL for ArcGIS REST API query with optional pagination offset."""
    base = info["base_url"]
    params = info.get("params")
    if params is None:
        return base  # type: ignore[no-any-return]
    parts: list[str] = []
    for key, val in params.items():
        if key == "resultRecordCount":
            if offset == 0:
                parts.append(f"resultRecordCount={val}")
            else:
                parts.append(f"resultOffset={offset}")
                parts.append(f"resultRecordCount={val}")
        else:
            parts.append(
                f"{urllib.parse.quote(key, safe='')}={urllib.parse.quote(str(val), safe='')}"
            )
    return f"{base}?{'&'.join(parts)}"


def fetch_url(url: str) -> bytes:
    """Fetch a URL once."""
    req = urllib.request.Request(  # noqa: S310
        url,
        headers={
            "User-Agent": "BrewGIS/1.0",
            "Accept": "application/json,text/html",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
        return resp.read()  # type: ignore[no-any-return]


def fetch_url_retry(url: str, retries: int = 3) -> bytes:
    """Fetch a URL with retries for transient failures."""
    for attempt in range(retries):
        try:
            return fetch_url(url)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            if attempt == retries - 1:
                raise
            wait = 2 * (attempt + 1)
            logger.warning("Retry %d/%d after %ds: %s", attempt + 1, retries, wait, exc)
            time.sleep(wait)
    return b""


def download_arcgis(info: dict[str, Any], filepath: Path) -> None:
    """Download data from an ArcGIS REST API FeatureServer with pagination."""
    has_more = True
    offset = 0
    all_features: list[dict[str, Any]] = []
    first_response: dict[str, Any] | None = None

    while has_more:
        url = build_url(info, offset)
        logger.info("Fetching (offset=%d)...", offset)
        data = fetch_url_retry(url)

        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            logger.exception(
                "JSON parse error, response: %s",
                data[:200].decode("utf-8", errors="replace"),
            )
            if not all_features:
                raise
            break

        raw_features = parsed.get("features", [])
        features = [arcgis_to_geojson_feature(f) for f in raw_features]
        if first_response is None:
            first_response = parsed

        if not features:
            logger.info("No more features")
            break

        all_features.extend(features)
        offset += len(features)

        exceeded = parsed.get("exceededTransferLimit", False)
        has_more = exceeded and info.get("needs_pagination", False)

    if not all_features:
        logger.warning("No features returned")
        empty = {"type": "FeatureCollection", "features": []}
        filepath.write_text(json.dumps(empty))
        return

    geojson: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": all_features,
    }
    if first_response and "crs" in first_response:
        geojson["crs"] = first_response["crs"]

    filepath.write_text(json.dumps(geojson))
    logger.info("Total: %d features", len(all_features))


def format_size(size: int) -> str:
    """Format byte count as human-readable string."""
    one_kb = 1024
    one_mb = one_kb * one_kb
    if size < one_kb:
        return f"{size} B"
    if size < one_mb:
        return f"{size / one_kb:.1f} KB"
    return f"{size / one_mb:.1f} MB"


def download_dataset(
    key: str,
    info: dict[str, Any],
    cache_dir: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Download a single dataset to the cache directory.

    Returns a dict with keys: ``key``, ``status`` (cached/downloaded/failed),
    ``file``, ``size``, and optionally ``error``.
    """
    filename = info["filename"]
    filepath = cache_dir / filename

    if filepath.exists() and not force:
        size = filepath.stat().st_size
        logger.info("[SKIP] Already cached (%s)", format_size(size))
        return {"key": key, "status": "cached", "file": str(filepath), "size": size}

    if info.get("params") is None:
        url = info["base_url"]
        logger.info("Downloading from %s...", url[:80])
        data = fetch_url(url)
        filepath.write_bytes(data)
    else:
        download_arcgis(info, filepath)
    size = filepath.stat().st_size
    logger.info("[OK] %s saved", format_size(size))
    return {
        "key": key,
        "status": "downloaded",
        "file": str(filepath),
        "size": size,
    }


def download_all_datasets(
    cache_dir: Path | None = None,
    *,
    force: bool = False,
    dataset: str | None = None,
    logger_fn: Any | None = None,
) -> list[dict[str, Any]]:
    """Download all (or a specific) Fresno demo dataset.

    Args:
        cache_dir: Directory to store cached files. Defaults to
            ``planning/fresno_demo`` under the project root.
        force: Re-download even if cached file exists.
        dataset: Specific dataset key to download, or ``None`` for all.
        logger_fn: Optional callable for status output (e.g. ``print``).

    Returns:
        List of result dicts (one per dataset).
    """
    dir_path = cache_dir or CACHE_DIR
    dir_path.mkdir(parents=True, exist_ok=True)

    all_datasets: dict[str, dict[str, Any]] = {}
    all_datasets.update(DATASETS)
    all_datasets.update(ADDITIONAL_DATASETS)

    keys = [dataset] if dataset else list(all_datasets)

    summary: list[dict[str, Any]] = []
    for key in keys:
        info = all_datasets[key]
        result = download_dataset(key, info, dir_path, force=force)
        summary.append(result)
        if logger_fn is not None:
            status = result["status"]
            file_str = result.get("file", "?")
            logger_fn(f"  {key}: {status} ({file_str})")

    return summary


def list_datasets() -> dict[str, tuple[str, str]]:
    """Return a dict mapping dataset keys to ``(description, source)`` tuples."""
    all_datasets: dict[str, dict[str, Any]] = {}
    all_datasets.update(DATASETS)
    all_datasets.update(ADDITIONAL_DATASETS)
    return {k: (v["description"], v["source"]) for k, v in all_datasets.items()}

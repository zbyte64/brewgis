"""Download and cache Fresno demo data from public sources.

Usage:
    python manage.py download_fresno_demo                     # download all datasets
    python manage.py download_fresno_demo --dataset parcels   # only parcels
    python manage.py download_fresno_demo --list-datasets     # list available datasets
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
from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser

logger = logging.getLogger(__name__)

CACHE_DIR = Path(settings.BASE_DIR) / "planning" / "fresno_demo"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

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

# ── Constraint datasets ─────────────────────────────────────────────

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


def _arcgis_to_geojson_feature(arcgis_feature: dict[str, Any]) -> dict[str, Any]:
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


def _build_url(info: dict[str, Any], offset: int = 0) -> str:
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


class Command(BaseCommand):
    help = "Download and cache Fresno demo data from public sources."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dataset",
            choices=list(DATASETS) + list(ADDITIONAL_DATASETS),
            default=None,
            help="Download only this dataset (default: all).",
        )
        parser.add_argument(
            "--list-datasets",
            action="store_true",
            help="List available datasets and exit.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-download even if cached file exists.",
        )
        parser.add_argument(
            "--cache-dir",
            default=str(CACHE_DIR),
            help=f"Cache directory (default: {CACHE_DIR}).",
        )

    def handle(self, **options: Any) -> None:
        if options["list_datasets"]:
            self._list_datasets()
            return

        cache_dir = Path(options["cache_dir"])
        cache_dir.mkdir(parents=True, exist_ok=True)
        force = options["force"]
        dataset = options["dataset"]

        all_datasets: dict[str, dict[str, Any]] = {}
        all_datasets.update(DATASETS)
        all_datasets.update(ADDITIONAL_DATASETS)

        keys = [dataset] if dataset else list(all_datasets)

        summary: list[dict[str, Any]] = []
        for key in keys:
            info = all_datasets[key]
            result = self._download_dataset(key, info, cache_dir, force)
            summary.append(result)

        self._print_summary(summary)

    def _list_datasets(self) -> None:
        self.stdout.write("\n=== Available Datasets ===\n")
        all_datasets: dict[str, dict[str, Any]] = {}
        all_datasets.update(DATASETS)
        all_datasets.update(ADDITIONAL_DATASETS)
        for key, info in all_datasets.items():
            self.stdout.write(f"  {key:<20} {info['description']:<50} {info['source']}")

    def _download_dataset(
        self,
        key: str,
        info: dict[str, Any],
        cache_dir: Path,
        force: bool = False,
    ) -> dict[str, Any]:
        filename = info["filename"]
        filepath = cache_dir / filename
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"Dataset: {key} — {info['description']}")
        self.stdout.write(f"Source:  {info['source']}")
        self.stdout.write(f"File:    {filepath}")

        if filepath.exists() and not force:
            size = filepath.stat().st_size
            self.stdout.write(f"  [SKIP] Already cached ({self._format_size(size)})")
            return {"key": key, "status": "cached", "file": str(filepath), "size": size}

        try:
            if info.get("params") is None:
                url = info["base_url"]
                self.stdout.write(f"  Downloading from {url[:80]}...")
                data = self._fetch_url(url)
                filepath.write_bytes(data)
            else:
                self._download_arcgis(info, filepath)
            size = filepath.stat().st_size
            self.stdout.write(f"  [OK] {self._format_size(size)} saved")
            return {
                "key": key,
                "status": "downloaded",
                "file": str(filepath),
                "size": size,
            }
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(f"  [FAIL] {exc}")
            return {
                "key": key,
                "status": "failed",
                "file": str(filepath),
                "error": str(exc),
            }

    def _download_arcgis(self, info: dict[str, Any], filepath: Path) -> None:
        """Download data from an ArcGIS REST API FeatureServer with pagination."""
        has_more = True
        offset = 0
        all_features: list[dict[str, Any]] = []
        first_response: dict[str, Any] | None = None

        while has_more:
            url = _build_url(info, offset)
            self.stdout.write(f"  Fetching (offset={offset})...")
            data = self._fetch_url_retry(url)

            try:
                parsed = json.loads(data)
            except json.JSONDecodeError as exc:
                self.stderr.write(f"  JSON parse error: {exc}")
                self.stderr.write(f"  Response preview: {data[:200].decode('utf-8', errors='replace')}")
                if not all_features:
                    raise
                break

            raw_features = parsed.get("features", [])
            features = [_arcgis_to_geojson_feature(f) for f in raw_features]
            if first_response is None:
                first_response = parsed

            if not features:
                self.stdout.write("  No more features")
                break

            all_features.extend(features)
            offset += len(features)

            exceeded = parsed.get("exceededTransferLimit", False)
            has_more = exceeded and info.get("needs_pagination", False)

        if not all_features:
            self.stdout.write("  [WARN] No features returned")
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
        self.stdout.write(f"  Total: {len(all_features)} features")

    def _fetch_url(self, url: str) -> bytes:
        """Fetch a URL once."""
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "BrewGIS/1.0",
                "Accept": "application/json,text/html",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()  # type: ignore[no-any-return]

    def _fetch_url_retry(self, url: str, retries: int = 3) -> bytes:
        """Fetch a URL with retries for transient failures."""
        for attempt in range(retries):
            try:
                return self._fetch_url(url)
            except (urllib.error.HTTPError, urllib.error.URLError) as exc:
                if attempt == retries - 1:
                    raise
                wait = 2 * (attempt + 1)
                self.stdout.write(
                    f"  Retry {attempt + 1}/{retries} after {wait}s: {exc}"
                )
                time.sleep(wait)
        return b""

    @staticmethod
    def _format_size(size: int) -> str:
        one_kb = 1024
        one_mb = one_kb * one_kb
        if size < one_kb:
            return f"{size} B"
        if size < one_mb:
            return f"{size / one_kb:.1f} KB"
        return f"{size / one_mb:.1f} MB"

    def _print_summary(self, summary: list[dict[str, Any]]) -> None:
        downloaded = [s for s in summary if s["status"] == "downloaded"]
        cached = [s for s in summary if s["status"] == "cached"]
        failed = [s for s in summary if s["status"] == "failed"]

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write("Summary:")
        if downloaded:
            self.stdout.write(f"  Downloaded: {len(downloaded)} datasets")
        if cached:
            self.stdout.write(f"  Already cached: {len(cached)} datasets")
        if failed:
            self.stdout.write(f"  Failed: {len(failed)} datasets")
            for s in failed:
                self.stdout.write(
                    f"    - {s['key']}: {s.get('error', 'unknown error')}"
                )

        total = sum(
            s.get("size", 0) for s in summary if s["status"] in ("downloaded", "cached")
        )
        self.stdout.write(f"  Total cache size: {self._format_size(total)}")
        self.stdout.write(f"  Cache directory: {CACHE_DIR}")

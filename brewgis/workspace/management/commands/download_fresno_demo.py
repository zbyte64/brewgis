"""Download and cache Fresno demo data from public sources.

Usage:
    python manage.py download_fresno_demo                     # download all datasets
    python manage.py download_fresno_demo --dataset parcels   # only parcels
    python manage.py download_fresno_demo --list-datasets     # list available datasets
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser

from brewgis.workspace.services.fresno_downloader import ADDITIONAL_DATASETS
from brewgis.workspace.services.fresno_downloader import CACHE_DIR
from brewgis.workspace.services.fresno_downloader import DATASETS
from brewgis.workspace.services.fresno_downloader import download_dataset
from brewgis.workspace.services.fresno_downloader import format_size
from brewgis.workspace.services.fresno_downloader import list_datasets

logger = logging.getLogger(__name__)


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
            self.stdout.write(f"\n{'=' * 60}")
            self.stdout.write(f"Dataset: {key} — {info['description']}")
            self.stdout.write(f"Source:  {info['source']}")
            self.stdout.write(f"File:    {cache_dir / info['filename']}")

            result = download_dataset(key, info, cache_dir, force=force)
            summary.append(result)

            status = result["status"]
            if status == "cached":
                self.stdout.write(
                    f"  [SKIP] Already cached ({format_size(result.get('size', 0))})"
                )
            elif status == "downloaded":
                self.stdout.write(f"  [OK] {format_size(result.get('size', 0))} saved")
            elif status == "failed":
                self.stderr.write(f"  [FAIL] {result.get('error', 'unknown error')}")

        self._print_summary(summary)

    def _list_datasets(self) -> None:
        self.stdout.write("\n=== Available Datasets ===\n")
        for key, (desc, source) in list_datasets().items():
            self.stdout.write(f"  {key:<20} {desc:<50} {source}")

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
        self.stdout.write(f"  Total cache size: {format_size(total)}")
        self.stdout.write(f"  Cache directory: {CACHE_DIR}")

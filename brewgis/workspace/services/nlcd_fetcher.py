"""NLCD (National Land Cover Database) raster downloader — DEPRECATED.

NLCD rasters are now fetched directly by DuckDB SQL models via httpfs
with cache_httpfs on-disk caching.  This module's download functions
have been removed; only file verification utilities remain.
"""

from __future__ import annotations

import contextlib
import logging
import zlib
from pathlib import Path

logger = logging.getLogger(__name__)


def _verify_cached_file(path: Path, expected_size: int | None = None) -> bool:
    """Verify a cached file exists and has positive size."""
    if not path.exists():
        return False
    if path.stat().st_size == 0:
        logger.warning("Cached file %s is empty, removing", path)
        path.unlink(missing_ok=True)
        return False
    if expected_size is not None and path.stat().st_size != expected_size:
        logger.warning(
            "Cached file %s size mismatch: expected %d, got %d",
            path,
            expected_size,
            path.stat().st_size,
        )
        path.unlink(missing_ok=True)
        return False
    return True


def _verify_cached_bytes(path: Path, size_path: Path, crc32_path: Path) -> bool:
    """Verify cached file size and CRC32 against companion files."""
    expected_size: int | None = None
    with contextlib.suppress(ValueError, OSError):
        expected_size = int(size_path.read_text().strip())

    if not _verify_cached_file(path, expected_size):
        return False

    if crc32_path.exists():
        try:
            expected_crc = int(crc32_path.read_text().strip())
            actual_crc = zlib.crc32(path.read_bytes())
            if actual_crc != expected_crc:
                logger.warning(
                    "Cached file %s CRC32 mismatch: expected %d, got %d",
                    path,
                    expected_crc,
                    actual_crc,
                )
                path.unlink(missing_ok=True)
                return False
        except (ValueError, OSError) as exc:
            logger.warning("Failed to read CRC32 for %s: %s", path, exc)
            return False

    return True

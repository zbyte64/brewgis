"""Filesystem-based LightGBM model cache.

Stores trained model pickles keyed by data hash in a shared directory.
Avoids hex-encoded pickle blobs in the database while preserving the
skip-retrain-when-data-hasn't-changed optimization.
"""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
from pathlib import Path

import pandas as pd
from sklearn.multioutput import MultiOutputRegressor

_CACHE_DIR: Path | None = None


def _ensure_cache_dir() -> Path:
    global _CACHE_DIR
    if _CACHE_DIR is None:
        cwd = Path(os.getcwd())
        _CACHE_DIR = cwd / "planning" / "lightgbm_cache"
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        logging.getLogger(__name__).info("LightGBM cache dir: %s", _CACHE_DIR)
    return _CACHE_DIR


def compute_data_hash(df: pd.DataFrame) -> str:
    """Compute a content hash of a DataFrame for cache key."""
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(df).to_numpy().tobytes())
    return h.hexdigest()


def try_load_cached(data_hash: str) -> MultiOutputRegressor | None:
    """Load a cached model from filesystem by data hash. Returns None on miss."""
    cache_path = _ensure_cache_dir() / f"{data_hash}.pkl"
    if cache_path.exists():
        logging.getLogger(__name__).info("Cache hit: %s", cache_path.name)
        try:
            return pickle.loads(cache_path.read_bytes())
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "Cache read failed for %s, retraining", cache_path.name
            )
            cache_path.unlink(missing_ok=True)
    return None


def save_model(model_obj: MultiOutputRegressor, data_hash: str) -> None:
    """Persist a trained model to filesystem cache."""
    cache_path = _ensure_cache_dir() / f"{data_hash}.pkl"
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps(model_obj))
    tmp.rename(cache_path)
    logging.getLogger(__name__).info("Cached model to %s", cache_path.name)

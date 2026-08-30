"""Filesystem-based LightGBM model cache.

Stores trained model pickles keyed by model type AND data hash in a shared
directory: ``{model_type}__{data_hash}.pkl``. Each pickle wraps the fitted
scikit-learn MultiOutputRegressor together with the ordered target column
names it was trained on, so inference models can map prediction columns back
to schema columns without assuming a fixed target set.

Type-keyed files fix a regression where every inference regressor loaded the
single most recently modified ``*.pkl`` — which was always the SQFT model
(trained last), so the DU and employment-ratio regressors predicted with the
wrong model.

NOTE: keep module level free of unpicklable objects (e.g. a module-level
``Logger``). SQLMesh serializes Python-model module namespaces; a logger
broke model loading with "cannot be serialized".
"""

from __future__ import annotations

import hashlib
import logging
import pickle
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import TypedDict
from typing import cast

import pandas as pd

if TYPE_CHECKING:
    from sklearn.multioutput import MultiOutputRegressor

_CACHE_DIR: Path | None = None


class ModelPayload(TypedDict):
    """Serialized regressor artifact: model plus its ordered target columns."""

    model_type: str
    targets: list[str]
    model: MultiOutputRegressor


def _ensure_cache_dir() -> Path:
    global _CACHE_DIR
    if _CACHE_DIR is None:
        cwd = Path.cwd()
        _CACHE_DIR = cwd / "planning" / "lightgbm_cache"
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        logging.getLogger(__name__).info("LightGBM cache dir: %s", _CACHE_DIR)
    return _CACHE_DIR


def compute_data_hash(df: pd.DataFrame) -> str:
    """Compute a content hash of a DataFrame for cache key."""
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(df).to_numpy().tobytes())
    return h.hexdigest()


def _model_path(model_type: str, data_hash: str) -> Path:
    """Path of the type-keyed cache file for a model type + data hash."""
    return _ensure_cache_dir() / f"{model_type}__{data_hash}.pkl"


def save_model(
    model_obj: MultiOutputRegressor,
    data_hash: str,
    model_type: str,
    targets: list[str],
) -> None:
    """Persist a trained model plus its target columns to the cache.

    Files are keyed by ``model_type`` so each regressor can load its own
    most recent model without cross-type contamination.
    """
    payload: ModelPayload = {
        "model_type": model_type,
        "targets": list(targets),
        "model": model_obj,
    }
    cache_path = _model_path(model_type, data_hash)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps(payload))
    tmp.rename(cache_path)
    logging.getLogger(__name__).info(
        "Cached %s model to %s", model_type, cache_path.name
    )


def try_load_cached(data_hash: str, model_type: str) -> ModelPayload | None:
    """Load the exact cached model for *model_type* and *data_hash*.

    Returns None on miss or if the cache entry is unreadable/corrupt (the
    corrupt file is removed so the next run retrains). Legacy untyped
    ``{data_hash}.pkl`` files from before type-keyed caching are ignored —
    their bare payloads carry no target mapping, so the next run retrains.
    """
    cache_path = _model_path(model_type, data_hash)
    if not cache_path.exists():
        return None
    logging.getLogger(__name__).info("Cache hit: %s", cache_path.name)
    try:
        raw: Any = pickle.loads(cache_path.read_bytes())  # noqa: S301
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "Cache read failed for %s, retraining", cache_path.name
        )
        cache_path.unlink(missing_ok=True)
        return None
    payload = _validate_payload(raw, model_type)
    if payload is None:
        logging.getLogger(__name__).warning(
            "Cache entry %s is corrupt, retraining", cache_path.name
        )
        cache_path.unlink(missing_ok=True)
        return None
    return payload


def load_latest_model(model_type: str) -> ModelPayload | None:
    """Load the most recently trained model of *model_type*.

    Scans ``{model_type}__*.pkl`` newest-first and returns the first valid
    payload; None if no valid model of that type exists.
    """
    cache_dir = _ensure_cache_dir()
    pkl_files = sorted(
        cache_dir.glob(f"{model_type}__*.pkl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in pkl_files:
        try:
            raw: Any = pickle.loads(path.read_bytes())  # noqa: S301
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "Ignoring unreadable cache file %s", path.name
            )
            continue
        payload = _validate_payload(raw, model_type)
        if payload is not None:
            logging.getLogger(__name__).info(
                "Loading %s model from %s (mtime=%s)",
                model_type,
                path.name,
                path.stat().st_mtime,
            )
            return payload
        logging.getLogger(__name__).warning(
            "Ignoring %s cache file %s with mismatched targets/outputs",
            model_type,
            path.name,
        )
    return None


def _validate_payload(raw: Any, model_type: str) -> ModelPayload | None:
    """Return *raw* as a ModelPayload if it is a valid artifact of *model_type*."""
    if not isinstance(raw, dict) or raw.get("model_type") != model_type:
        return None
    model_obj = raw.get("model")
    targets = raw.get("targets")
    if model_obj is None or not isinstance(targets, list):
        return None
    if not hasattr(model_obj, "estimators_") or not all(
        isinstance(t, str) for t in targets
    ):
        return None
    if len(targets) != len(model_obj.estimators_):
        return None
    return cast(
        "ModelPayload",
        {
            "model_type": model_type,
            "targets": list(targets),
            "model": model_obj,
        },
    )

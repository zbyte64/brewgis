"""Shared batch prediction for LightGBM regressors to avoid OOM on large inference.

Streams inference data from the caller-supplied iterator, predicting one batch at
a time and yielding partial results so the full prediction array is never held in
memory.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

    import numpy as np
    import pandas as pd
    from sklearn.multioutput import MultiOutputRegressor


def _batch_size() -> int:
    """Configured batch size from env, default 50K."""
    try:
        return int(os.environ.get("LGBM_INFERENCE_BATCH_SIZE", "50000"))
    except ValueError:
        return 50000


def predict_in_batches(
    data_stream: Iterator[pd.DataFrame],
    model: MultiOutputRegressor,
    feature_fn: Callable[[pd.DataFrame], pd.DataFrame],
) -> Iterator[tuple[pd.DataFrame, np.ndarray]]:
    """Predict on batches from *data_stream*, yielding (apns, y_pred) for each.

    The caller loads inference data incrementally via *data_stream*. For each
    raw-data batch the function builds the feature matrix via *feature_fn*,
    predicts with *model*, and yields the ``apn`` column DataFrame plus the
    predictions array.  No full-dataset prediction array is ever assembled.
    """
    for batch in data_stream:
        apns = batch[["apn"]].copy()
        x_batch = feature_fn(batch)
        y_batch = model.predict(x_batch)
        yield apns, y_batch

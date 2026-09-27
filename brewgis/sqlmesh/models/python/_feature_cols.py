"""Shared feature-contract helpers for the LightGBM regressors.

Every regressor builds the same feature matrix — its ``NUMERIC_FEATURES`` plus
one ``ldc_*`` column per land-development category seen at fit time plus
``_RESNET_PC_COLS`` — twice: in the trainer that fits the model, and in the
region inference model that consumes the artifact the trainer cached. The
trainer records the fitted feature list inside the artifact
(``feature_names_in_``) and inference reads it back from there, so the serving
side never carries a second, drifting copy of the contract. The helpers here
let the cache loader reject an artifact the current feature set cannot build
instead of handing its feature list to ``model.predict``.

Minimal module with no third-party imports — SQLMesh serializes python model
module namespaces and rejects unpicklable values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Sequence

# PCA components of the ResNet-34 NAIP embedding, produced by the
# parcel_resnet_features adapter.
_RESNET_PC_COLS = [f"pc{i + 1:02d}" for i in range(32)]

# Land-development-category one-hot prefix and the category used when the
# parcel has none. Both trainers and both inference queries COALESCE
# land_development_category with LDC_FALLBACK, so a NULL parcel falls in the
# same bucket at fit and predict time.
LDC_PREFIX = "ldc_"
LDC_FALLBACK = "standard"


def fitted_feature_names(model: Any) -> list[str] | None:
    """Return the ordered feature names *model* was fitted on, or None.

    Both trainers fit a ``MultiOutputRegressor`` on a DataFrame, so scikit-learn
    records the feature names on each wrapped estimator as
    ``feature_names_in_``.
    """
    estimators = getattr(model, "estimators_", None)
    if not estimators:
        return None
    names = getattr(estimators[0], "feature_names_in_", None)
    return None if names is None else [str(name) for name in names]


def unbuildable_feature_columns(
    expected_cols: Iterable[str],
    numeric_features: Sequence[str],
) -> list[str]:
    """Columns *expected_cols* needs that the current feature set cannot build.

    The builder emits *numeric_features*, ``_RESNET_PC_COLS`` and one
    ``LDC_PREFIX`` column per category seen at fit time (categories absent from
    the inference data stay zero), so any other column means the artifact was
    fitted on a feature set this code no longer produces.
    """
    buildable = set(numeric_features) | set(_RESNET_PC_COLS)
    return [
        col
        for col in expected_cols
        if col not in buildable and not col.startswith(LDC_PREFIX)
    ]

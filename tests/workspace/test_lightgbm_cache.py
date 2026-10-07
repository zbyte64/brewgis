"""Unit tests for the LightGBM model cache (type-keyed pickle storage).

Regression guards for two inference failures, both caused by ``load_latest_model``
handing an artifact to code that could not use it:

* type mixing — every inference regressor loaded the single newest ``*.pkl``,
  always the SQFT model (trained last), so the DU and employment-ratio
  regressors predicted with the wrong model;
* feature drift — after the resnet feature set changed, the pre-change
  artifacts were still loaded and their fitted feature list was fed to a
  query that no longer produced those columns.

Type-keyed files + wrapped target lists fix the first; the feature-contract
check fixes the second.
"""

from __future__ import annotations

import os
import pickle
import time
import types
from typing import TYPE_CHECKING
from typing import Any

import pandas as pd
import pytest

from brewgis.sqlmesh.models.python import _cache
from brewgis.sqlmesh.models.python._feature_cols import _RESNET_PC_COLS
from brewgis.sqlmesh.models.python._feature_cols import LDC_PREFIX

if TYPE_CHECKING:
    from pathlib import Path


# Stand-in for a regressor's NUMERIC_FEATURES: the check under test is generic
# over the caller's list, so a short one keeps the fixtures readable.
NUMERIC_FEATURES = ["lot_size_acres", "building_count", "max_levels"]


class TestLightgbmCache:
    """Tests for save_model / try_load_cached / load_latest_model."""

    @pytest.fixture(autouse=True)
    def _isolated_cache_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Point the cache at a throwaway directory per test."""
        monkeypatch.setattr(_cache, "_ensure_cache_dir", lambda: tmp_path)

    @staticmethod
    def _fake_model(n_targets: int, features: list[str] | None) -> Any:
        """Minimal stand-in for a fitted MultiOutputRegressor."""
        estimator = types.SimpleNamespace(feature_names_in_=features)
        return types.SimpleNamespace(estimators_=[estimator for _ in range(n_targets)])

    @staticmethod
    def _current_features() -> list[str]:
        """Feature list the current feature set produces."""
        return [*NUMERIC_FEATURES, f"{LDC_PREFIX}urban", *_RESNET_PC_COLS]

    def test_type_isolation(self) -> None:
        """load_latest_model must only return models of the requested type."""
        features = self._current_features()
        _cache.save_model(
            self._fake_model(5, features), "hashA", "du", ["du_detsf_sl"] * 5
        )
        _cache.save_model(
            self._fake_model(15, features), "hashB", "sqft", ["bldg_sqft_detsf_sl"] * 15
        )
        _cache.save_model(
            self._fake_model(4, features),
            "hashC",
            "emp_ratios",
            ["emp_ret_per_acre"] * 4,
        )

        du = _cache.load_latest_model("du", NUMERIC_FEATURES)
        sqft = _cache.load_latest_model("sqft", NUMERIC_FEATURES)
        emp = _cache.load_latest_model("emp_ratios", NUMERIC_FEATURES)

        assert du is not None
        assert len(du["targets"]) == 5
        assert len(list(du["model"].estimators_)) == 5
        assert du["model_type"] == "du"
        assert sqft is not None
        assert len(sqft["targets"]) == 15
        assert emp is not None
        assert len(emp["targets"]) == 4

    def test_newest_model_of_type_wins(self, tmp_path: Path) -> None:
        """Within a type, the most recently saved file is loaded."""
        features = self._current_features()
        _cache.save_model(self._fake_model(5, features), "old", "du", ["a"] * 5)
        _cache.save_model(self._fake_model(5, features), "new", "du", ["b"] * 5)
        now = time.time()
        os.utime(tmp_path / "du__old.pkl", (now - 100, now - 100))
        os.utime(tmp_path / "du__new.pkl", (now, now))

        du = _cache.load_latest_model("du", NUMERIC_FEATURES)

        assert du is not None
        assert du["targets"] == ["b"] * 5

    def test_try_load_cached_scoped_by_type_and_hash(self) -> None:
        """Exact type+hash hits; wrong type or hash misses."""
        _cache.save_model(
            self._fake_model(5, self._current_features()), "hashX", "du", ["a"] * 5
        )

        assert _cache.try_load_cached("hashX", "du") is not None
        assert _cache.try_load_cached("hashX", "sqft") is None
        assert _cache.try_load_cached("nope", "du") is None

    def test_mismatched_targets_outputs_skipped(self) -> None:
        """A file whose target list length differs from outputs is ignored."""
        features = self._current_features()
        _cache.save_model(self._fake_model(5, features), "bad", "du", ["a"] * 4)
        assert _cache.load_latest_model("du", NUMERIC_FEATURES) is None

        # ...and a valid file of the same type still wins when present
        _cache.save_model(self._fake_model(5, features), "good", "du", ["a"] * 5)
        du = _cache.load_latest_model("du", NUMERIC_FEATURES)
        assert du is not None
        assert len(du["targets"]) == 5

    def test_legacy_untyped_pickle_ignored(self, tmp_path: Path) -> None:
        """Pre-refactor bare pickles must never be loaded.

        Two cases: untyped ``{hash}.pkl`` names (never matched by the
        type-keyed glob) and type-named files containing a bare model
        (no wrapped target list — rejected by payload validation).
        """
        bare = self._fake_model(15, None)
        (tmp_path / "deadbeef.pkl").write_bytes(pickle.dumps(bare))
        (tmp_path / "du__deadbeef.pkl").write_bytes(pickle.dumps(bare))

        assert _cache.load_latest_model("du", NUMERIC_FEATURES) is None
        assert _cache.load_latest_model("sqft", NUMERIC_FEATURES) is None
        assert _cache.try_load_cached("deadbeef", "sqft") is None

    def test_data_hash_covers_column_names(self) -> None:
        """Renaming features must invalidate cached models keyed on the old names."""
        df = pd.DataFrame({"lot_size_acres": [1.0, 2.0], "building_count": [1, 2]})
        renamed = df.rename(columns={"lot_size_acres": "parcel_acres"})

        config = {"params": {"n_estimators": 100}}
        assert _cache.compute_data_hash(df, config) != _cache.compute_data_hash(
            renamed, config
        )
        assert _cache.compute_data_hash(df, config) == _cache.compute_data_hash(
            df.copy(), config
        )

    def test_data_hash_covers_fit_config(self) -> None:
        """The same data fitted another way must not reuse the old artifact."""
        df = pd.DataFrame({"lot_size_acres": [1.0, 2.0], "building_count": [1, 2]})
        unweighted = {"params": {"n_estimators": 100}, "sample_weight": None}
        weighted = {
            "params": {"n_estimators": 100},
            "sample_weight": "total_footprint_sqft",
        }

        assert _cache.compute_data_hash(df, unweighted) != _cache.compute_data_hash(
            df, weighted
        )

    def test_stale_feature_artifact_skipped(self, tmp_path: Path) -> None:
        """An artifact the current feature set cannot build loses to a usable one.

        The stale artifact is the *newest* file, so the scan has to keep
        looking rather than stop at the first valid payload.
        """
        _cache.save_model(
            self._fake_model(4, ["lot_size_acres", "lu_A1", "zone_A"]),
            "stale",
            "emp_ratios",
            ["stale"] * 4,
        )
        _cache.save_model(
            self._fake_model(4, self._current_features()),
            "fresh",
            "emp_ratios",
            ["fresh"] * 4,
        )
        now = time.time()
        os.utime(tmp_path / "emp_ratios__stale.pkl", (now, now))
        os.utime(tmp_path / "emp_ratios__fresh.pkl", (now - 100, now - 100))

        payload = _cache.load_latest_model("emp_ratios", NUMERIC_FEATURES)

        assert payload is not None
        assert payload["targets"] == ["fresh"] * 4

    def test_stale_feature_artifact_alone_yields_no_model(self) -> None:
        """With only pre-change artifacts cached, the caller must retrain."""
        _cache.save_model(
            self._fake_model(4, ["lot_size_acres", "lu_A1", "zone_A"]),
            "stale",
            "emp_ratios",
            ["emp_ret_per_acre"] * 4,
        )

        assert _cache.load_latest_model("emp_ratios", NUMERIC_FEATURES) is None

    def test_artifact_without_fitted_feature_names_skipped(self) -> None:
        """An artifact that records no feature names can never be verified."""
        _cache.save_model(
            self._fake_model(4, None), "nameless", "du", ["du_detsf_sl"] * 4
        )

        assert _cache.load_latest_model("du", NUMERIC_FEATURES) is None

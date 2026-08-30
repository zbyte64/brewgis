"""Unit tests for the LightGBM model cache (type-keyed pickle storage).

Regression guard for the Res Parcel Area inflation: all three inference
regressors previously loaded the single newest ``*.pkl`` — always the SQFT
model, since it trains last — so the DU and employment-ratio regressors
predicted with the wrong model. Type-keyed files + wrapped target lists
prevent cross-type contamination; these tests pin the cache contract.
"""

from __future__ import annotations

import os
import pickle
import time
import types
from typing import TYPE_CHECKING
from typing import Any

import pytest

from brewgis.sqlmesh.models.python import _cache

if TYPE_CHECKING:
    from pathlib import Path


class TestLightgbmCache:
    """Tests for save_model / try_load_cached / load_latest_model."""

    @pytest.fixture(autouse=True)
    def _isolated_cache_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Point the cache at a throwaway directory per test."""
        monkeypatch.setattr(_cache, "_ensure_cache_dir", lambda: tmp_path)

    @staticmethod
    def _fake_model(n_targets: int) -> Any:
        """Minimal stand-in for a fitted MultiOutputRegressor."""
        return types.SimpleNamespace(estimators_=[object() for _ in range(n_targets)])

    def test_type_isolation(self) -> None:
        """load_latest_model must only return models of the requested type."""
        _cache.save_model(self._fake_model(5), "hashA", "du", ["du_detsf_sl"] * 5)
        _cache.save_model(
            self._fake_model(15), "hashB", "sqft", ["bldg_sqft_detsf_sl"] * 15
        )
        _cache.save_model(
            self._fake_model(4), "hashC", "emp_ratios", ["emp_ret_per_acre"] * 4
        )

        du = _cache.load_latest_model("du")
        sqft = _cache.load_latest_model("sqft")
        emp = _cache.load_latest_model("emp_ratios")

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
        _cache.save_model(self._fake_model(5), "old", "du", ["a"] * 5)
        _cache.save_model(self._fake_model(5), "new", "du", ["b"] * 5)
        now = time.time()
        os.utime(tmp_path / "du__old.pkl", (now - 100, now - 100))
        os.utime(tmp_path / "du__new.pkl", (now, now))

        du = _cache.load_latest_model("du")

        assert du is not None
        assert du["targets"] == ["b"] * 5

    def test_try_load_cached_scoped_by_type_and_hash(self) -> None:
        """Exact type+hash hits; wrong type or hash misses."""
        _cache.save_model(self._fake_model(5), "hashX", "du", ["a"] * 5)

        assert _cache.try_load_cached("hashX", "du") is not None
        assert _cache.try_load_cached("hashX", "sqft") is None
        assert _cache.try_load_cached("nope", "du") is None

    def test_mismatched_targets_outputs_skipped(self) -> None:
        """A file whose target list length differs from outputs is ignored."""
        _cache.save_model(self._fake_model(5), "bad", "du", ["a"] * 4)
        assert _cache.load_latest_model("du") is None

        # ...and a valid file of the same type still wins when present
        _cache.save_model(self._fake_model(5), "good", "du", ["a"] * 5)
        du = _cache.load_latest_model("du")
        assert du is not None
        assert len(du["targets"]) == 5

    def test_legacy_untyped_pickle_ignored(self, tmp_path: Path) -> None:
        """Pre-refactor bare pickles must never be loaded.

        Two cases: untyped ``{hash}.pkl`` names (never matched by the
        type-keyed glob) and type-named files containing a bare model
        (no wrapped target list — rejected by payload validation).
        """
        (tmp_path / "deadbeef.pkl").write_bytes(pickle.dumps(self._fake_model(15)))
        (tmp_path / "du__deadbeef.pkl").write_bytes(pickle.dumps(self._fake_model(15)))

        assert _cache.load_latest_model("du") is None
        assert _cache.load_latest_model("sqft") is None
        assert _cache.try_load_cached("deadbeef", "sqft") is None

"""Integration tests for ResNet-34 forward pass and PCA compression.

These tests verify the core ML pipeline operations without requiring
NAIP downloads or a PostGIS database. They depend on torch and torchvision
being installed.
"""

from __future__ import annotations

import importlib

import numpy as np
import pytest
from sklearn.decomposition import IncrementalPCA

torch = pytest.importorskip("torch")
torchvision_models = pytest.importorskip("torchvision.models")
resnet_bft_features = pytest.importorskip(
    "brewgis.sqlmesh.models.python.resnet_bft_features"
)


class TestResNetBackbone:
    """Verify ResNet-34 backbone forward pass."""

    def test_backbone_output_shape(self) -> None:
        """ResNet backbone should produce (N, 512) embedding vectors."""
        m = torchvision_models.resnet34(
            weights=torchvision_models.ResNet34_Weights.IMAGENET1K_V1
        )
        m.eval()
        backbone = torch.nn.Sequential(*list(m.children())[:-1])

        batch = torch.randn(10, 3, 224, 224)
        with torch.no_grad():
            output = backbone(batch).flatten(1)

        assert output.shape == (10, 512)
        assert output.dtype == torch.float32

    def test_batched_inference_consistency(self) -> None:
        """Same input should produce same output regardless of batch size."""
        m = torchvision_models.resnet34(
            weights=torchvision_models.ResNet34_Weights.IMAGENET1K_V1
        )
        m.eval()
        backbone = torch.nn.Sequential(*list(m.children())[:-1])

        chips = torch.randn(5, 3, 224, 224)

        # Run as one batch of 5
        with torch.no_grad():
            out_full = backbone(chips).flatten(1)

        # Run as 5 individual batches
        outs = []
        for i in range(5):
            with torch.no_grad():
                out_single = backbone(chips[i : i + 1]).flatten(1)
            outs.append(out_single)
        out_individual = torch.cat(outs, dim=0)

        assert torch.allclose(out_full, out_individual, atol=1e-5)

    def test_single_chip_inference(self) -> None:
        """A single (1, 3, 224, 224) chip should produce (1, 512) embedding."""
        m = torchvision_models.resnet34(
            weights=torchvision_models.ResNet34_Weights.IMAGENET1K_V1
        )
        m.eval()
        backbone = torch.nn.Sequential(*list(m.children())[:-1])

        chip = torch.randn(1, 3, 224, 224)
        with torch.no_grad():
            output = backbone(chip).flatten(1)

        assert output.shape == (1, 512)
        assert output.dtype == torch.float32


class TestIncrementalPCA:
    """Verify IncrementalPCA compression from ResNet embeddings."""

    def test_pca_reduces_dimension(self) -> None:
        """PCA should reduce 512-d embeddings to 32-d features."""
        rng = np.random.default_rng(42)
        embeddings = rng.standard_normal((100, 512)).astype(np.float32)

        pca = IncrementalPCA(n_components=32, batch_size=10000)
        pca.fit(embeddings)

        features = pca.transform(embeddings)
        assert features.shape == (100, 32)
        # Modern scikit-learn preserves the input dtype (float32 in,
        # float32 out) instead of always upcasting to float64 — not that
        # it matters for us either way, since resnet_bft_features.py casts
        # the output to float32 explicitly regardless (see its line 362).
        assert features.dtype == np.float32

    def test_pca_components_shape(self) -> None:
        """PCA components should have shape (32, 512)."""
        rng = np.random.default_rng(42)
        embeddings = rng.standard_normal((100, 512)).astype(np.float32)

        pca = IncrementalPCA(n_components=32, batch_size=10000)
        pca.fit(embeddings)

        assert pca.components_.shape == (32, 512)

    def test_pca_explained_variance_positive(self) -> None:
        """Explained variance should be positive and decreasing."""
        rng = np.random.default_rng(42)
        embeddings = rng.standard_normal((100, 512)).astype(np.float32)

        pca = IncrementalPCA(n_components=32, batch_size=10000)
        pca.fit(embeddings)

        explained_ratio = pca.explained_variance_ratio_
        assert len(explained_ratio) == 32
        assert np.all(explained_ratio > 0)

    def test_pca_silently_clamps_when_too_few_samples(self) -> None:
        """Document current scikit-learn behavior: IncrementalPCA no longer
        raises for too-few-samples — it silently clamps components_ to
        n_samples while `n_components_` still reports the requested value,
        so transform() returns fewer columns than the caller expects. This
        is exactly the gap `_check_min_pca_samples` (tested below) exists
        to catch before it reaches scikit-learn."""
        pca = IncrementalPCA(n_components=32, batch_size=10000)
        pca.fit(np.random.randn(10, 512))
        assert pca.n_components_ == 32
        assert pca.components_.shape == (10, 512)

    def test_transform_output_all_finite(self) -> None:
        """All transformed feature values should be finite."""
        rng = np.random.default_rng(42)
        embeddings = rng.standard_normal((100, 512)).astype(np.float32)

        pca = IncrementalPCA(n_components=32, batch_size=10000)
        pca.fit(embeddings)

        features = pca.transform(embeddings)
        assert np.all(np.isfinite(features))


class TestCheckMinPcaSamples:
    """Verify the _check_min_pca_samples guard and its env-var toggle.

    scikit-learn stopped raising for too-few-samples (see
    TestIncrementalPCA.test_pca_silently_clamps_when_too_few_samples), so
    this guard restores a fail-fast error at the application level —
    behind a toggle in case it ever needs to be turned off in production
    without a code change.
    """

    def _reload_with_env(self, monkeypatch: pytest.MonkeyPatch, value: str | None):
        """Set (or clear) the toggle env var and reload the module so its
        module-level `_ENFORCE_MIN_PCA_SAMPLES` picks up the new value."""
        if value is None:
            monkeypatch.delenv("RESNET_BFT_ENFORCE_MIN_PCA_SAMPLES", raising=False)
        else:
            monkeypatch.setenv("RESNET_BFT_ENFORCE_MIN_PCA_SAMPLES", value)
        importlib.reload(resnet_bft_features)

    @pytest.fixture(autouse=True)
    def _restore_module_state(self, monkeypatch: pytest.MonkeyPatch):
        """Reload the module once more after each test so a later test file
        (or a later run of this one) doesn't inherit a monkeypatched env
        var's effect after monkeypatch itself has already reverted it."""
        yield
        importlib.reload(resnet_bft_features)

    def test_enforced_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no env var set, too few samples raises RuntimeError."""
        self._reload_with_env(monkeypatch, None)
        with pytest.raises(RuntimeError, match="33 required for PCA"):
            resnet_bft_features._check_min_pca_samples(10)

    def test_enforced_allows_enough_samples(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With enough samples, the guard is a no-op."""
        self._reload_with_env(monkeypatch, None)
        resnet_bft_features._check_min_pca_samples(33)
        resnet_bft_features._check_min_pca_samples(1000)

    def test_toggle_disables_the_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """RESNET_BFT_ENFORCE_MIN_PCA_SAMPLES=0 bypasses the check entirely —
        the escape hatch for if this guard ever misfires in production."""
        self._reload_with_env(monkeypatch, "0")
        resnet_bft_features._check_min_pca_samples(10)  # does not raise

    def test_toggle_value_other_than_1_disables_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Any value other than the literal "1" disables enforcement —
        matching the codebase's existing `== "1"` env-flag convention
        (see brewgis/sqlmesh/config.py's SQLMESH_DUCKDB_READONLY)."""
        self._reload_with_env(monkeypatch, "false")
        resnet_bft_features._check_min_pca_samples(10)  # does not raise


class TestEmbeddingsCacheKey:
    """Verify the chip-embeddings cache key covers the parcel set.

    The key must identify *what was extracted*, which is the imagery tiles
    AND the parcels chipped from them. Keying on the COG URLs alone let a
    region whose parcel extent grew (a wider fresno region bbox still
    resolves to the same NAIP tiles) reuse embeddings extracted for the
    previous parcel set, silently dropping every parcel added since instead
    of recomputing.
    """

    _COG_HASH = "b262d4555c90b9a6de40d7beeae8c1cd4d5264730ba98f45331afc7be1193451"

    def test_same_imagery_and_parcels_reuse_the_cache(self) -> None:
        """Identical inputs must hit the cached embeddings."""
        parcels = ["apn-1", "apn-2", "apn-3"]
        assert resnet_bft_features._embeddings_cache_key(
            self._COG_HASH, parcels
        ) == resnet_bft_features._embeddings_cache_key(self._COG_HASH, parcels)

    def test_key_ignores_parcel_order(self) -> None:
        """Parcel order is a query artifact, not part of the extraction —
        a different row order must not discard a cached extraction."""
        assert resnet_bft_features._embeddings_cache_key(
            self._COG_HASH, ["apn-3", "apn-1", "apn-2"]
        ) == resnet_bft_features._embeddings_cache_key(
            self._COG_HASH, ["apn-1", "apn-2", "apn-3"]
        )

    def test_grown_parcel_extent_invalidates_the_cache(self) -> None:
        """Adding parcels over unchanged imagery must force a recompute."""
        assert resnet_bft_features._embeddings_cache_key(
            self._COG_HASH, ["apn-1", "apn-2", "apn-3"]
        ) != resnet_bft_features._embeddings_cache_key(
            self._COG_HASH, ["apn-1", "apn-2", "apn-3", "apn-4"]
        )

    def test_same_parcels_over_different_imagery_invalidate_the_cache(self) -> None:
        """New imagery means new chips, even for an unchanged parcel set."""
        parcels = ["apn-1", "apn-2"]
        assert resnet_bft_features._embeddings_cache_key(
            self._COG_HASH, parcels
        ) != resnet_bft_features._embeddings_cache_key("0" * 64, parcels)

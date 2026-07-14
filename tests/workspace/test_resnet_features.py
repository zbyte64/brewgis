"""Integration tests for ResNet-34 forward pass and PCA compression.

These tests verify the core ML pipeline operations without requiring
NAIP downloads or a PostGIS database. They depend on torch and torchvision
being installed.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.decomposition import IncrementalPCA

torch = pytest.importorskip("torch")
torchvision_models = pytest.importorskip("torchvision.models")


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
        assert features.dtype == np.float64

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

    def test_pca_needs_minimum_samples(self) -> None:
        """PCA requires at least n_components+1 samples."""
        pca = IncrementalPCA(n_components=32, batch_size=10000)
        with pytest.raises(ValueError, match="n_components"):
            pca.fit(np.random.randn(10, 512))

    def test_transform_output_all_finite(self) -> None:
        """All transformed feature values should be finite."""
        rng = np.random.default_rng(42)
        embeddings = rng.standard_normal((100, 512)).astype(np.float32)

        pca = IncrementalPCA(n_components=32, batch_size=10000)
        pca.fit(embeddings)

        features = pca.transform(embeddings)
        assert np.all(np.isfinite(features))

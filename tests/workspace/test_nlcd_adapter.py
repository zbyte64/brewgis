"""Tests for NLCD and OSM adapters (land classification, irrigation, intersection density)."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from brewgis.workspace.services.base_canvas_adapters import (
    NullIntersectionDensitySource,
)
from brewgis.workspace.services.base_canvas_adapters import NullIrrigationSource
from brewgis.workspace.services.base_canvas_adapters import NullLandUseSource
from brewgis.workspace.services.nlcd_fetcher import _verify_cached_file

if TYPE_CHECKING:
    from pathlib import Path


class TestNullLandUseSource:
    """Null sources should report unavailable."""

    def test_not_available(self) -> None:
        assert not NullLandUseSource().available
        assert not NullIrrigationSource().available
        assert not NullIntersectionDensitySource().available


class TestNLCDClassification:
    """NLCD land cover classification rules."""

    def test_urban_from_developed(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import _nlcd_majority_class

        pixels = np.array([22, 22, 22, 41, 81], dtype=np.uint8)
        assert _nlcd_majority_class(pixels) == "urban"

    def test_industrial_from_high_intensity(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import _nlcd_majority_class

        pixels = np.array([24, 24, 24, 22], dtype=np.uint8)
        assert _nlcd_majority_class(pixels) == "industrial"

    def test_agricultural_from_crops(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import _nlcd_majority_class

        pixels = np.array([81, 81, 82, 21], dtype=np.uint8)
        assert _nlcd_majority_class(pixels) == "agricultural"

    def test_natural_from_forest(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import _nlcd_majority_class

        pixels = np.array([41, 42, 43, 51], dtype=np.uint8)
        assert _nlcd_majority_class(pixels) == "natural"

    def test_empty_pixels_returns_unknown(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import _nlcd_majority_class

        assert _nlcd_majority_class(None) == "unknown"
        assert _nlcd_majority_class(np.array([])) == "unknown"

    def test_impervious_fraction_computed(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import (
            _estimate_nlcd_impervious_fraction,
        )

        pixels = np.array([21, 22, 23, 24], dtype=np.uint8)
        expected = (0.10 + 0.30 + 0.60 + 0.85) / 4
        result = _estimate_nlcd_impervious_fraction(pixels)
        assert abs(result - expected) < 0.01

    def test_impervious_empty_returns_zero(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import (
            _estimate_nlcd_impervious_fraction,
        )

        assert _estimate_nlcd_impervious_fraction(None) == 0.0
        assert _estimate_nlcd_impervious_fraction(np.array([])) == 0.0


class TestAssessorClassification:
    """Assessor use code classification rules."""

    def test_residential_codes(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import classify_land_development

        assert classify_land_development(assessor_use_code="R") == "urban"
        assert classify_land_development(assessor_use_code="R1") == "urban"
        assert classify_land_development(assessor_use_code="RES") == "urban"
        assert classify_land_development(assessor_use_code="SFR") == "urban"
        assert classify_land_development(assessor_use_code="MFR") == "urban"
        assert classify_land_development(assessor_use_code="CONDO") == "urban"

    def test_commercial_codes(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import classify_land_development

        assert classify_land_development(assessor_use_code="COM") == "industrial"
        assert classify_land_development(assessor_use_code="RET") == "industrial"

    def test_industrial_codes(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import classify_land_development

        assert classify_land_development(assessor_use_code="IND") == "industrial"
        assert classify_land_development(assessor_use_code="MFG") == "industrial"
        assert classify_land_development(assessor_use_code="WARE") == "industrial"

    def test_agricultural_codes(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import classify_land_development

        assert classify_land_development(assessor_use_code="AG") == "agricultural"
        assert classify_land_development(assessor_use_code="FARM") == "agricultural"

    def test_default_to_urban(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import classify_land_development

        assert classify_land_development() == "urban"
        assert classify_land_development(assessor_use_code="UNKNOWN") == "urban"

    def test_nlcd_majority_used_when_no_code(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import classify_land_development

        result = classify_land_development(nlcd_majority="agricultural")
        assert result == "agricultural"

class TestVerifyCachedFile:
    """Tests for _verify_cached_file integrity check."""

    def test_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.img"
        assert _verify_cached_file(missing) is False

    def test_empty_file_removed(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.img"
        empty.write_bytes(b"")
        assert _verify_cached_file(empty) is False
        assert not empty.exists()

    def test_size_mismatch_removed(self, tmp_path: Path) -> None:
        f = tmp_path / "test.img"
        f.write_bytes(b"some data")
        assert _verify_cached_file(f, expected_size=999) is False
        assert not f.exists()

    def test_valid_file(self, tmp_path: Path) -> None:
        f = tmp_path / "valid.img"
        f.write_bytes(b"valid content")
        assert _verify_cached_file(f) is True
        assert f.exists()

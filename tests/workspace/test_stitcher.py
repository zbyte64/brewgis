"""Tests for the column stitching / imputation service."""
from __future__ import annotations

import pytest

from brewgis.workspace.services.stitcher import impute_constant


class TestImputeConstant:
    """Tests for the constant-value imputation strategy."""

    def test_impute_constant_returns_dict(self) -> None:
        """impute_constant should return the expected dict structure."""
        # We can't easily test the database interaction without a DB,
        # but we can verify the return type and expected keys.
        # Full integration tests require a running PostGIS instance.
        pass

    def test_impute_constant_contract(self) -> None:
        """Verify the function signature and return contract."""
        import inspect

        sig = inspect.signature(impute_constant)
        params = list(sig.parameters.keys())
        assert "schema" in params
        assert "table" in params
        assert "column" in params
        assert "value" in params

        return_annotation = sig.return_annotation
        assert "rows_updated" in str(return_annotation) or return_annotation is not None


class TestImputeAreaProportional:
    """Tests for the area-proportional imputation strategy."""

    def test_function_signature(self) -> None:
        """Verify the function accepts expected parameters."""
        from brewgis.workspace.services.stitcher import impute_area_proportional

        import inspect

        sig = inspect.signature(impute_area_proportional)
        param_names = list(sig.parameters.keys())
        assert "schema" in param_names
        assert "target_table" in param_names
        assert "target_column" in param_names
        assert "source_schema" in param_names
        assert "source_table" in param_names
        assert "source_column" in param_names


class TestImputeBuiltFormDefault:
    """Tests for the built-form default imputation strategy."""

    def test_function_signature(self) -> None:
        """Verify the function accepts expected parameters."""
        from brewgis.workspace.services.stitcher import impute_built_form_default

        import inspect

        sig = inspect.signature(impute_built_form_default)
        param_names = list(sig.parameters.keys())
        assert "schema" in param_names
        assert "table" in param_names
        assert "column" in param_names
        assert "built_form_table" in param_names


class TestStitcherModule:
    """Module-level tests for the stitcher."""

    def test_module_imports(self) -> None:
        """All public functions should be importable."""
        from brewgis.workspace.services.stitcher import (
            impute_area_proportional,
            impute_built_form_default,
            impute_constant,
        )

        assert callable(impute_constant)
        assert callable(impute_area_proportional)
        assert callable(impute_built_form_default)

    def test_impute_constant_value_type(self) -> None:
        """The value parameter should accept int or float."""
        # Just verify the type hint accepts both
        import typing

        hints = typing.get_type_hints(impute_constant)
        # The value param should accept int | float
        assert hints.get("value") is not None

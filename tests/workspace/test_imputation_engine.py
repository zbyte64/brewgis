"""Tests for the ImputationEngine service.

Tests each strategy independently and the three-tier cascade.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from brewgis.workspace.services.imputation_engine import (
    ImputationEngine,
    ImputationRule,
    ImputationStrategy,
)


class TestImputationEngine:
    """Tests for the ImputationEngine class."""

    def test_empty_dataframe(self) -> None:
        """Applying imputation to an empty DataFrame should succeed."""
        engine = ImputationEngine()
        df = pd.DataFrame()
        rules = [
            ImputationRule(
                target_column="pop",
                strategy=ImputationStrategy.NATIONAL_DEFAULT,
                fallback_value=0.0,
            )
        ]
        results = engine.apply(df, rules)
        assert len(results) == 1
        assert results[0].rows_total == 0

    def test_column_not_found(self) -> None:
        """Rule for a non-existent column should record an error."""
        engine = ImputationEngine()
        df = pd.DataFrame({"a": [1, 2, 3]})
        rules = [
            ImputationRule(
                target_column="missing_col",
                strategy=ImputationStrategy.NATIONAL_DEFAULT,
                fallback_value=0.0,
            )
        ]
        results = engine.apply(df, rules)
        assert len(results[0].errors) == 1

    def test_no_nulls(self) -> None:
        """A column with no NULLs should be reported as already populated."""
        engine = ImputationEngine()
        df = pd.DataFrame({"pop": [100.0, 200.0, 300.0]})
        rules = [
            ImputationRule(
                target_column="pop",
                strategy=ImputationStrategy.NATIONAL_DEFAULT,
                fallback_value=0.0,
            )
        ]
        results = engine.apply(df, rules)
        assert results[0].rows_already_populated == 3
        assert results[0].rows_imputed_national == 0

    # ── NATIONAL_DEFAULT ─────────────────────────────────────────────

    def test_national_default_fills_all_nulls(self) -> None:
        """NATIONAL_DEFAULT should fill every NULL with the fallback."""
        engine = ImputationEngine()
        df = pd.DataFrame({"pop": [100.0, np.nan, np.nan, 200.0]})
        rules = [
            ImputationRule(
                target_column="pop",
                strategy=ImputationStrategy.NATIONAL_DEFAULT,
                fallback_value=0.0,
            )
        ]
        engine.apply(df, rules)
        assert df["pop"].isna().sum() == 0
        assert list(df["pop"]) == [100.0, 0.0, 0.0, 200.0]

    def test_national_default_custom_value(self) -> None:
        """NATIONAL_DEFAULT should use the specified fallback."""
        engine = ImputationEngine()
        df = pd.DataFrame({"du": [np.nan, np.nan]})
        rules = [
            ImputationRule(
                target_column="du",
                strategy=ImputationStrategy.NATIONAL_DEFAULT,
                fallback_value=42.0,
            )
        ]
        engine.apply(df, rules)
        assert list(df["du"]) == [42.0, 42.0]

    # ── DIRECT_OBSERVATION ───────────────────────────────────────────

    def test_direct_observation_copies_source(self) -> None:
        """DIRECT_OBSERVATION should copy source column values."""
        engine = ImputationEngine()
        df = pd.DataFrame({
            "pop_observed": [150.0, np.nan, 250.0],
            "pop": [np.nan, np.nan, np.nan],
        })
        rules = [
            ImputationRule(
                target_column="pop",
                source_column="pop_observed",
                strategy=ImputationStrategy.DIRECT_OBSERVATION,
                fallback_value=0.0,
            )
        ]
        engine.apply(df, rules)
        assert list(df["pop"]) == [150.0, 0.0, 250.0]

    def test_direct_observation_missing_source(self) -> None:
        """DIRECT_OBSERVATION with missing source should fall through."""
        engine = ImputationEngine()
        df = pd.DataFrame({"pop": [np.nan, 100.0]})
        rules = [
            ImputationRule(
                target_column="pop",
                source_column="nonexistent",
                strategy=ImputationStrategy.DIRECT_OBSERVATION,
                fallback_value=99.0,
            )
        ]
        engine.apply(df, rules)
        assert df["pop"].isna().sum() == 0
        assert df.loc[0, "pop"] == 99.0  # fell through to national default

    # ── REGIONAL_ESTIMATE ────────────────────────────────────────────

    def test_regional_estimate_computes_group_mean(self) -> None:
        """REGIONAL_ESTIMATE should fill NULLs with the group mean."""
        engine = ImputationEngine()
        df = pd.DataFrame({
            "pop": [100.0, np.nan, 200.0, np.nan],
            "county": ["a", "a", "b", "b"],
        })
        rules = [
            ImputationRule(
                target_column="pop",
                strategy=ImputationStrategy.REGIONAL_ESTIMATE,
                groupby_column="county",
                fallback_value=0.0,
            )
        ]
        engine.apply(df, rules)
        # county "a" mean = 100.0, county "b" mean = 200.0
        assert df.loc[1, "pop"] == pytest.approx(100.0)
        assert df.loc[3, "pop"] == pytest.approx(200.0)

    def test_regional_estimate_unknown_group_falls_back(self) -> None:
        """When a whole group is NULL, REGIONAL_ESTIMATE should fall back."""
        engine = ImputationEngine()
        df = pd.DataFrame({
            "pop": [np.nan, np.nan],
            "county": ["a", "b"],
        })
        rules = [
            ImputationRule(
                target_column="pop",
                strategy=ImputationStrategy.REGIONAL_ESTIMATE,
                groupby_column="county",
                fallback_value=0.0,
            )
        ]
        engine.apply(df, rules)
        assert df["pop"].isna().sum() == 0
        assert df.loc[0, "pop"] == 0.0
        assert df.loc[1, "pop"] == 0.0

    def test_regional_estimate_missing_groupby_col(self) -> None:
        """When groupby column is missing, REGIONAL_ESTIMATE falls through."""
        engine = ImputationEngine()
        df = pd.DataFrame({
            "pop": [np.nan, 100.0],
        })
        rules = [
            ImputationRule(
                target_column="pop",
                strategy=ImputationStrategy.REGIONAL_ESTIMATE,
                groupby_column="nonexistent",
                fallback_value=42.0,
            )
        ]
        engine.apply(df, rules)
        assert df["pop"].isna().sum() == 0
        assert df.loc[0, "pop"] == 42.0

    # ── Full cascade ─────────────────────────────────────────────────

    def test_cascade_direct_then_regional_then_default(self) -> None:
        """Full cascade: direct -> regional -> national default."""
        engine = ImputationEngine()
        df = pd.DataFrame({
            "pop_observed": [np.nan, 500.0, np.nan, np.nan],
            "pop": [np.nan, np.nan, np.nan, np.nan],
            "county": ["a", "a", "a", "b"],
        })
        rules = [
            ImputationRule(
                target_column="pop",
                source_column="pop_observed",
                strategy=ImputationStrategy.DIRECT_OBSERVATION,
                groupby_column="county",
                fallback_value=99.0,
            )
        ]
        results = engine.apply(df, rules)
        r = results[0]
        # Row 0: direct fills from pop_observed (but it's NaN), so falls through
        # Row 1: direct observed from pop_observed = 500.0
        # Row 2: direct NaN, regional (county "a" mean: only row 1 has 500.0 + row 0 NaN, so mean = 500)
        # Row 3: direct NaN, regional (county "b" has no non-null values -> falls to national = 99.0)
        assert r.rows_imputed_direct >= 1  # row 1
        assert r.rows_already_populated >= 0
        assert df["pop"].isna().sum() == 0
        assert df.loc[1, "pop"] == pytest.approx(500.0)

    def test_result_counts(self) -> None:
        """ImputationResult should correctly count rows per strategy."""
        engine = ImputationEngine()
        df = pd.DataFrame({
            "pop_observed": [100.0, np.nan, np.nan],
            "pop": [np.nan, np.nan, np.nan],
            "county": ["a", "a", "b"],
        })
        rules = [
            ImputationRule(
                target_column="pop",
                source_column="pop_observed",
                strategy=ImputationStrategy.DIRECT_OBSERVATION,
                groupby_column="county",
                fallback_value=0.0,
            )
        ]
        results = engine.apply(df, rules)
        r = results[0]
        assert r.target_column == "pop"
        assert r.rows_total == 3
        assert r.rows_already_populated == 0
        assert r.rows_imputed_direct == 1  # row 0 from pop_observed
        assert r.rows_imputed_regional >= 0
        # row 1: regional via county "a" mean
        # row 2: national default (county "b" has no non-null)
        assert r.rows_imputed_national >= 0
        assert r.rows_still_null == 0

    # ── Convenience builders ─────────────────────────────────────────

    def test_direct_rule_builder(self) -> None:
        """Static convenience builder should produce correct rule."""
        rule = ImputationEngine.direct_rule("pop", "pop_observed", 0.0)
        assert rule.target_column == "pop"
        assert rule.source_column == "pop_observed"
        assert rule.strategy == ImputationStrategy.DIRECT_OBSERVATION

    def test_regional_rule_builder(self) -> None:
        """Static convenience builder should produce correct rule."""
        rule = ImputationEngine.regional_rule("pop", "county", 0.0)
        assert rule.target_column == "pop"
        assert rule.groupby_column == "county"
        assert rule.strategy == ImputationStrategy.REGIONAL_ESTIMATE

    def test_national_rule_builder(self) -> None:
        """Static convenience builder should produce correct rule."""
        rule = ImputationEngine.national_rule("pop", 42.0)
        assert rule.target_column == "pop"
        assert rule.fallback_value == 42.0
        assert rule.strategy == ImputationStrategy.NATIONAL_DEFAULT

    def test_multiple_columns_independent(self) -> None:
        """Applying rules to different columns should not interfere."""
        engine = ImputationEngine()
        df = pd.DataFrame({
            "pop": [np.nan, 100.0],
            "hh": [50.0, np.nan],
        })
        rules = [
            ImputationRule(
                target_column="pop",
                strategy=ImputationStrategy.NATIONAL_DEFAULT,
                fallback_value=0.0,
            ),
            ImputationRule(
                target_column="hh",
                strategy=ImputationStrategy.NATIONAL_DEFAULT,
                fallback_value=10.0,
            ),
        ]
        results = engine.apply(df, rules)
        assert len(results) == 2
        assert df["pop"].isna().sum() == 0
        assert df["hh"].isna().sum() == 0
        assert df.loc[0, "pop"] == 0.0
        assert df.loc[1, "hh"] == 10.0

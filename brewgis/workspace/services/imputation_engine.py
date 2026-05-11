"""Imputation Engine - three-tier cascade for filling NULLs in base canvas data.

Strategy cascade order:

    1. DIRECT_OBSERVATION -- use a source column value directly (e.g., copy
       ``pop_observed`` -> ``pop``). This is always preferred when available.
    2. REGIONAL_ESTIMATE -- compute the mean of non-null values within a
       geography group (e.g., county-level average). Applied when direct
       observation is missing.
    3. NATIONAL_DEFAULT -- apply a hardcoded fallback constant for columns
       that lack both direct and regional data.

The engine operates on a GeoDataFrame in memory. It records for each imputed
cell which strategy was used (for auditing / debugging).
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd
try:
    import polars as pl
except ImportError:
    pl = None

logger = logging.getLogger(__name__)


class ImputationStrategy(enum.Enum):
    """Priority-ordered imputation strategies."""

    DIRECT_OBSERVATION = 1
    REGIONAL_ESTIMATE = 2
    NATIONAL_DEFAULT = 3


# Sentinel for "no imputation was needed" — the value was already populated.
_NOT_IMPUTED = 0
# Sentinel for "no strategy could fill this cell" — should not happen when
# NATIONAL_DEFAULT is the final fallback.
_STILL_NULL = -1


@dataclass
class ImputationRule:
    """One imputation rule: maps *target_column* to its fill strategy chain.

    Parameters
    ----------
    target_column : str
        Name of the column to impute.
    source_column : str | None
        Column name providing DIRECT_OBSERVATION data (if any).
    strategy : ImputationStrategy
        Highest-priority strategy to attempt.
    fallback_value : float | None
        NATIONAL_DEFAULT constant (only relevant when strategy is
        NATIONAL_DEFAULT or as the final tier in the cascade).
    groupby_column : str | None
        Geography column for REGIONAL_ESTIMATE averaging (e.g. ``"county"``).
    """

    target_column: str
    source_column: str | None = None
    strategy: ImputationStrategy = ImputationStrategy.NATIONAL_DEFAULT
    fallback_value: float | None = 0.0
    groupby_column: str | None = None


@dataclass
class ImputationResult:
    """Result of applying imputation to a single column."""

    target_column: str
    rows_total: int
    rows_already_populated: int
    rows_imputed_direct: int = 0
    rows_imputed_regional: int = 0
    rows_imputed_national: int = 0
    rows_still_null: int = 0
    errors: list[str] = field(default_factory=list)


class ImputationEngine:
    """Three-tier cascade imputation engine.

    Usage::

        engine = ImputationEngine()
        rules = [
            ImputationRule("pop", source_column="pop_observed",
                           strategy=ImputationStrategy.DIRECT_OBSERVATION,
                           fallback_value=0.0),
            ImputationRule("hh", strategy=ImputationStrategy.REGIONAL_ESTIMATE,
                           groupby_column="county", fallback_value=0.0),
            ImputationRule("intersection_density",
                           strategy=ImputationStrategy.NATIONAL_DEFAULT,
                           fallback_value=12.5),
        ]
        results = engine.apply(df, rules)
    """

    def apply(
        self,
        df: pd.DataFrame | Any,
        rules: list[ImputationRule],
    ) -> list[ImputationResult]:
        """Apply a list of imputation rules to *df* in order.

        Accepts both pandas DataFrames (default) and Polars DataFrames
        (when polars is installed). The pandas path is unchanged.
        """
        if pl is not None and isinstance(df, pl.DataFrame):
            return self._apply_polars(df, rules)
        return self._apply_pandas(df, rules)

    def _apply_pandas(
        self,
        df: pd.DataFrame,
        rules: list[ImputationRule],
    ) -> list[ImputationResult]:
        """Apply a list of imputation rules using pandas-native operations."""
        results: list[ImputationResult] = []
        for rule in rules:
            result = self._apply_rule(df, rule)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Per-rule cascade
    # ------------------------------------------------------------------

    def _apply_rule(
        self,
        df: pd.DataFrame,
        rule: ImputationRule,
    ) -> ImputationResult:
        col = rule.target_column
        if col not in df.columns:
            return ImputationResult(
                target_column=col,
                rows_total=len(df),
                rows_already_populated=0,
                errors=[f"Column '{col}' not found in DataFrame"],
            )

        total = len(df)
        null_mask = df[col].isna()

        if not null_mask.any():
            return ImputationResult(
                target_column=col,
                rows_total=total,
                rows_already_populated=total,
            )

        result = ImputationResult(
            target_column=col,
            rows_total=total,
            rows_already_populated=(~null_mask).sum(),
        )

        remaining = null_mask.copy()

        # Tier 1: DIRECT_OBSERVATION
        if rule.strategy.value <= ImputationStrategy.DIRECT_OBSERVATION.value:
            if rule.source_column and rule.source_column in df.columns:
                direct_mask = remaining & df[rule.source_column].notna()
                if direct_mask.any():
                    df.loc[direct_mask, col] = df.loc[direct_mask, rule.source_column]
                    result.rows_imputed_direct = int(direct_mask.sum())
                    remaining = df[col].isna()
                    logger.debug(
                        "DIRECT_OBSERVATION filled %d/%d NULLs in '%s' from '%s'",
                        direct_mask.sum(),
                        null_mask.sum(),
                        col,
                        rule.source_column,
                    )
            else:
                logger.debug(
                    "Source column '%s' not found for DIRECT_OBSERVATION on '%s'",
                    rule.source_column,
                    col,
                )

        # Tier 2: REGIONAL_ESTIMATE (mean within group)
        if rule.strategy.value <= ImputationStrategy.REGIONAL_ESTIMATE.value:
            if remaining.any() and rule.groupby_column:
                if rule.groupby_column in df.columns:
                    region_filled = self._impute_regional_average(
                        df, col, remaining, rule.groupby_column
                    )
                    result.rows_imputed_regional = region_filled
                    remaining = df[col].isna()
                else:
                    logger.debug(
                        "Groupby column '%s' not found for REGIONAL_ESTIMATE on '%s'",
                        rule.groupby_column,
                        col,
                    )

        # Tier 3: NATIONAL_DEFAULT
        if rule.strategy.value <= ImputationStrategy.NATIONAL_DEFAULT.value:
            if remaining.any() and rule.fallback_value is not None:
                df.loc[remaining, col] = rule.fallback_value
                result.rows_imputed_national = int(remaining.sum())
                remaining = df[col].isna()
                logger.debug(
                    "NATIONAL_DEFAULT filled %d NULLs in '%s' with %s",
                    int(remaining.sum()),
                    col,
                    rule.fallback_value,
                )

        still_null = int(remaining.sum())
        if still_null:
            result.rows_still_null = still_null
            logger.warning(
                "%d NULLs remain in '%s' after full imputation cascade",
                still_null,
                col,
            )

        return result

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    def _impute_regional_average(
        self,
        df: pd.DataFrame,
        col: str,
        null_mask: pd.Series,
        groupby_column: str,
    ) -> int:
        """Fill NULLs in *col* with the group mean of non-null values.

        Returns the number of rows filled.
        """
        # Compute per-group mean from non-null rows
        group_means: pd.Series = df.groupby(groupby_column)[col].transform("mean")

        # Use global mean when a whole group is NULL
        global_mean = df[col].mean()
        fill_values = group_means.where(group_means.notna(), global_mean)

        # Where the group mean is also NaN (entire group NULL), use global mean
        # If global mean is also NaN, use 0 as last resort
        fill_values = fill_values.fillna(0.0)

        filled_mask = null_mask & fill_values.notna()
        count = int(filled_mask.sum())
        if count:
            df.loc[filled_mask, col] = fill_values[filled_mask]
        return count
    # ------------------------------------------------------------------
    # Polars implementations
    # ------------------------------------------------------------------

    def _apply_polars(
        self,
        df: pl.DataFrame,
        rules: list[ImputationRule],
    ) -> list[ImputationResult]:
        """Apply imputation rules using Polars-native operations."""
        results: list[ImputationResult] = []
        for rule in rules:
            result = self._apply_rule_polars(df, rule)
            results.append(result)
        return results

    def _apply_rule_polars(
        self,
        df: pl.DataFrame,
        rule: ImputationRule,
    ) -> ImputationResult:
        """Apply a single imputation rule using Polars-native operations."""
        col = rule.target_column
        total = df.height

        if col not in df.columns:
            return ImputationResult(
                target_column=col,
                rows_total=total,
                rows_already_populated=0,
                errors=[f"Column '{col}' not found in DataFrame"],
            )

        null_count = df[col].null_count()
        if null_count == 0:
            return ImputationResult(
                target_column=col,
                rows_total=total,
                rows_already_populated=total,
            )

        rows_populated = total - null_count
        result = ImputationResult(
            target_column=col,
            rows_total=total,
            rows_already_populated=rows_populated,
        )

        remaining_null_count = null_count

        # Tier 1: DIRECT_OBSERVATION
        if rule.strategy.value <= ImputationStrategy.DIRECT_OBSERVATION.value:
            if rule.source_column and rule.source_column in df.columns:
                src_null_count = df[rule.source_column].null_count()
                direct_count = null_count - src_null_count if src_null_count < null_count else 0
                if direct_count > 0:
                    df = df.with_columns(
                        pl.when(pl.col(col).is_null())
                        .then(pl.col(rule.source_column))
                        .otherwise(pl.col(col))
                        .alias(col)
                    )
                    result.rows_imputed_direct = direct_count
                    remaining_null_count = df[col].null_count()
                    logger.debug(
                        "DIRECT_OBSERVATION filled %d/%d NULLs in '%s' from '%s'",
                        direct_count,
                        null_count,
                        col,
                        rule.source_column,
                    )

        # Tier 2: REGIONAL_ESTIMATE (mean within group)
        if rule.strategy.value <= ImputationStrategy.REGIONAL_ESTIMATE.value:
            if remaining_null_count > 0 and rule.groupby_column:
                if rule.groupby_column in df.columns:
                    region_filled = self._impute_regional_average_polars(df, col, rule.groupby_column)
                    result.rows_imputed_regional = region_filled
                    remaining_null_count = df[col].null_count()
                else:
                    logger.debug(
                        "Groupby column '%s' not found for REGIONAL_ESTIMATE on '%s'",
                        rule.groupby_column,
                        col,
                    )

        # Tier 3: NATIONAL_DEFAULT
        if rule.strategy.value <= ImputationStrategy.NATIONAL_DEFAULT.value:
            if remaining_null_count > 0 and rule.fallback_value is not None:
                df = df.with_columns(
                    pl.col(col).fill_null(rule.fallback_value)
                )
                filled = remaining_null_count
                result.rows_imputed_national = filled
                remaining_null_count = 0
                logger.debug(
                    "NATIONAL_DEFAULT filled %d NULLs in '%s' with %s",
                    filled,
                    col,
                    rule.fallback_value,
                )

        if remaining_null_count > 0:
            result.rows_still_null = remaining_null_count
            logger.warning(
                "%d NULLs remain in '%s' after full imputation cascade",
                remaining_null_count,
                col,
            )

        return result

    def _impute_regional_average_polars(
        self,
        df: pl.DataFrame,
        col: str,
        groupby_column: str,
    ) -> int:
        """Fill NULLs in *col* with the group mean of non-null values (Polars).

        Returns the number of rows filled.
        """
        # Compute per-group mean
        global_mean = df[col].mean()
        if global_mean is None or (isinstance(global_mean, float) and global_mean != global_mean):
            global_mean = 0.0

        group_means = df.group_by(groupby_column).agg(pl.col(col).mean().alias("_group_mean"))

        # Join group means back and fill NULLs
        before_null = df[col].null_count()
        df = df.join(group_means, on=groupby_column, how="left").with_columns(
            pl.when(pl.col(col).is_null() & pl.col("_group_mean").is_not_null())
            .then(pl.col("_group_mean"))
            .when(pl.col(col).is_null())
            .then(global_mean)
            .otherwise(pl.col(col))
            .alias(col)
        ).drop("_group_mean")

        after_null = df[col].null_count()
        return before_null - after_null

    # ------------------------------------------------------------------
    # Convenience builders
    # ------------------------------------------------------------------

    @staticmethod
    def direct_rule(
        target_column: str,
        source_column: str,
        fallback_value: float = 0.0,
    ) -> ImputationRule:
        """Build a DIRECT_OBSERVATION rule that falls back to NATIONAL_DEFAULT."""
        return ImputationRule(
            target_column=target_column,
            source_column=source_column,
            strategy=ImputationStrategy.DIRECT_OBSERVATION,
            fallback_value=fallback_value,
        )

    @staticmethod
    def regional_rule(
        target_column: str,
        groupby_column: str = "county",
        fallback_value: float = 0.0,
    ) -> ImputationRule:
        """Build a REGIONAL_ESTIMATE rule that falls back to NATIONAL_DEFAULT."""
        return ImputationRule(
            target_column=target_column,
            strategy=ImputationStrategy.REGIONAL_ESTIMATE,
            groupby_column=groupby_column,
            fallback_value=fallback_value,
        )

    @staticmethod
    def national_rule(
        target_column: str,
        fallback_value: float = 0.0,
    ) -> ImputationRule:
        """Build a NATIONAL_DEFAULT rule (hardcoded constant)."""
        return ImputationRule(
            target_column=target_column,
            strategy=ImputationStrategy.NATIONAL_DEFAULT,
            fallback_value=fallback_value,
        )

"""Classification methods for symbology.

Given column statistics and a requested number of classes, each classifier
produces break points, human-readable labels, and per-class feature counts.

Supported methods
=================
- **natural_breaks** / **jenks** — Jenks natural breaks optimisation
- **equal_interval** — linear division of [min, max)
- **quantile** — NTILE-based equal-count binning
- **logarithmic** — log-scale division (for skewed distributions)
- **std_deviation** — breaks at standard-deviation intervals from the mean
- **manual** — user-provided break points
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import deal
from django.db import connection


@dataclass
class ClassificationResult:
    """Result of a classification operation.

    Attributes
    ----------
    method:
        The algorithm used (e.g. ``"quantile"``).
    breaks:
        ``num_classes + 1`` break points defining class boundaries.
        ``breaks[i]`` is the inclusive lower bound of class *i*,
        ``breaks[i+1]`` is the exclusive upper bound (except the last
        class which is inclusive on both ends).
    labels:
        Human-readable labels for each class.
    counts:
        Number of features falling into each class (may be estimated
        from the histogram if exact counts are not available).
    """

    method: str
    breaks: list[float]
    labels: list[str] = field(default_factory=list)
    counts: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_Classifier = Callable[..., ClassificationResult]

_FMT_THRESHOLD = 1_000_000
_FMT_SMALL_THRESHOLD = 0.01


@deal.post(lambda result: isinstance(result, str))
def _fmt(val: float) -> str:
    """Format a break value for a human-readable label."""
    if math.isnan(val):
        return "NaN"
    if abs(val) >= _FMT_THRESHOLD or (abs(val) > 0 and abs(val) < _FMT_SMALL_THRESHOLD):
        return f"{val:.2e}"
    if val == int(val):
        return str(int(val))
    return f"{val:.2f}"


@deal.pre(lambda breaks: len(breaks) >= 1)
@deal.ensure(lambda breaks, result: len(result) == len(breaks) - 1)
def _make_labels(breaks: list[float]) -> list[str]:
    """Build human-readable labels from break points."""
    labels: list[str] = []
    for i in range(len(breaks) - 1):
        lo = _fmt(breaks[i])
        hi = _fmt(breaks[i + 1])
        labels.append(f"{lo} - {hi}")
    return labels


# ---------------------------------------------------------------------------
# Classifier implementations
# --------------------------------------------------------------------------


@deal.ensure(
    lambda min_val, max_val, num_classes, result: (
        num_classes < 1 or len(result) == num_classes + 1
    )
)
@deal.ensure(
    lambda min_val, max_val, num_classes, result: (
        num_classes < 1 or (result[0] == min_val and math.isclose(result[-1], max_val))
    )
)
@deal.pre(
    lambda min_val, max_val, num_classes: (
        max_val >= min_val
        and all(math.isfinite(v) for v in [min_val, max_val])
        and num_classes <= 100
    )
)
def _equal_interval_breaks(
    min_val: float,
    max_val: float,
    num_classes: int,
) -> list[float]:
    """Divide [min, max] into *num_classes* bins of equal width."""
    if num_classes < 1:
        return [min_val]
    if max_val == min_val:
        return [min_val] * (num_classes + 1)
    step = (max_val - min_val) / num_classes
    breaks = [min_val + step * i for i in range(num_classes + 1)]
    breaks[-1] = max_val  # clamp final break to max_val (avoids FP precision drift)
    return breaks


def _quantile_breaks(
    schema: str, table: str, column: str, num_classes: int
) -> list[float]:
    """NTILE-based quantile classification using a single SQL query."""
    if num_classes < 1:
        sql = (
            f'SELECT MIN("{column}")::double precision '
            f'FROM "{schema}"."{table}" '
            f'WHERE "{column}" IS NOT NULL'
        )
        with connection.cursor() as cursor:
            cursor.execute(sql)
            (min_val,) = cursor.fetchone()
        return [min_val]

    sql = f"""
        WITH ranked AS (
            SELECT "{column}"::double precision AS val,
                   NTILE({num_classes}) OVER (ORDER BY "{column}") AS tile
            FROM "{schema}"."{table}"
            WHERE "{column}" IS NOT NULL
        )
        SELECT MIN(val), MAX(val), tile
        FROM ranked
        GROUP BY tile
        ORDER BY tile
    """
    with connection.cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()

    if not rows:
        return [0.0]

    breaks = [rows[0][0]]
    for _, max_v, _ in rows[:-1]:
        breaks.append(max_v)
    breaks.append(rows[-1][1])

    # Deduplicate adjacent identical breaks
    cleaned = [breaks[0]]
    for b in breaks[1:]:
        if b != cleaned[-1]:
            cleaned.append(b)
    return cleaned


@deal.ensure(
    lambda min_val, max_val, num_classes, result: (
        num_classes < 1 or (result[0] <= min_val and result[-1] >= max_val)
    )
)
@deal.pre(
    lambda min_val, max_val, num_classes: (
        all(math.isfinite(v) for v in [min_val, max_val]) and num_classes <= 100
    )
)
def _logarithmic_breaks(
    min_val: float, max_val: float, num_classes: int
) -> list[float]:
    """Log-scale division."""
    if num_classes < 1:
        return [min_val]
    if max_val <= min_val:
        return [min_val] * (num_classes + 1)

    offset = 0.0
    lo = min_val
    hi = max_val
    if lo <= 0:
        offset = -lo + 1.0
        lo += offset
        hi += offset

    log_lo = math.log10(lo) if lo > 0 else 0
    log_hi = math.log10(hi) if hi > 0 else 0
    step = (log_hi - log_lo) / num_classes

    result = [10 ** (log_lo + step * i) - offset for i in range(num_classes + 1)]
    result[0] = min_val
    result[-1] = max_val
    return result


@deal.pre(
    lambda mean, stddev, num_classes: (
        stddev >= 0 and num_classes >= 1 and num_classes <= 100
    )
)
def _std_deviation_breaks(mean: float, stddev: float, num_classes: int) -> list[float]:
    """Breaks at standard-deviation intervals from the mean."""
    half = num_classes // 2
    breaks = [mean - half * stddev]
    for i in range(1, num_classes + 1):
        breaks.append(mean + (i - half) * stddev)
    return breaks


@deal.ensure(lambda data, lo, hi, result: result >= 0)
@deal.pre(lambda data, lo, hi: all(math.isfinite(x) for x in data[lo-1:hi]))
@deal.pre(lambda data, lo, hi: 1 <= lo <= hi)
def _sum_squared_diffs(data: list[float], lo: int, hi: int) -> float:
    """Compute sum of squared differences from the mean for ``data[lo:hi]``.

    Indices are 1-based per the Jenks algorithm convention.
    """
    if hi <= lo:
        return 0.0
    segment = data[lo - 1 : hi]
    if not segment:
        return 0.0
    mu = sum(segment) / len(segment)
    return sum((x - mu) ** 2 for x in segment)


def _natural_breaks_jenks(values: list[float], num_classes: int) -> list[float]:
    """Jenks natural breaks optimisation.

    O(k n^2) where *k* = num_classes.  For large value sets, downsample
    or use the histogram-based approximation instead.
    """
    if num_classes < 1:
        return [values[0]] if values else [0.0]
    if len(values) <= num_classes:
        return sorted(set(values))

    data = sorted(values)
    n = len(data)
    k = num_classes

    # Matrices: lower class limits and variance
    lower: list[list[float]] = [[0.0] * (n + 1) for _ in range(k + 1)]
    variance: list[list[float]] = [[0.0] * (n + 1) for _ in range(k + 1)]

    for i in range(1, k + 1):
        lower[i][1] = 1
        variance[i][1] = 0.0
    for j in range(2, n + 1):
        variance[1][j] = _sum_squared_diffs(data, 1, j)

    for i in range(2, k + 1):
        for j in range(2, n + 1):
            variance[i][j] = float("inf")
            for s in range(int(lower[i - 1][j - 1]), j):
                ssd = variance[i - 1][s] + _sum_squared_diffs(data, s + 1, j)
                if variance[i][j] > ssd:
                    variance[i][j] = ssd
                    lower[i][j] = s

    # Reconstruct breaks from lower matrix
    k_current = k
    n_current = n
    breaks: list[float] = [data[-1]]
    while k_current > 0:
        idx = int(lower[k_current][n_current])
        breaks.append(data[idx - 1] if idx > 0 else data[0])
        n_current = idx
        k_current -= 1

    breaks.reverse()
    return breaks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_METHOD_DISTINCT_THRESHOLD = 50


def classify(
    stats: Any,
    method: str = "quantile",
    num_classes: int = 5,
    schema: str | None = None,
    table: str | None = None,
    column: str | None = None,
    manual_breaks: list[float] | None = None,
) -> ClassificationResult:
    """Classify a column into *num_classes* bins using *method*.

    Parameters
    ----------
    stats:
        A ``ColumnStatistics`` instance (or compatible duck-type with
        ``min_value``, ``max_value``, ``mean``, ``stddev``, ``count``,
        ``histogram`` attributes).
    method:
        One of ``"natural_breaks"``, ``"jenks"``, ``"equal_interval"``,
        ``"quantile"``, ``"logarithmic"``, ``"std_deviation"``, or
        ``"manual"``.
    num_classes:
        Number of output classes.
    schema, table, column:
        Required for ``"quantile"`` classification (database query).
    manual_breaks:
        Break points (n+1 values) when *method* is ``"manual"``.

    Returns
    -------
    ClassificationResult
    """
    breaks: list[float]

    if method in ("natural_breaks", "jenks"):
        # Use histogram midpoints for Jenks if available
        if stats.histogram:
            mids = [(b.min_val + b.max_val) / 2.0 for b in stats.histogram]
            weighted: list[float] = []
            for i, b in enumerate(stats.histogram):
                weighted.extend([mids[i]] * min(b.count, _METHOD_DISTINCT_THRESHOLD))
            vals = weighted or [stats.min_value or 0, stats.max_value or 0]
        else:
            vals = [stats.min_value or 0, stats.max_value or 0]

        # If we have fewer distinct values than classes, interpolate
        if len(set(vals)) < num_classes:
            lo = min(vals)
            hi = max(vals)
            if lo == hi:
                vals = [lo]
            else:
                vals = [
                    lo + (hi - lo) * i / (num_classes * 5 - 1)
                    for i in range(num_classes * 5)
                ]
        breaks = _natural_breaks_jenks(vals, num_classes)

    elif method == "equal_interval":
        breaks = _equal_interval_breaks(
            stats.min_value or 0,
            stats.max_value or 0,
            num_classes,
        )

    elif method == "quantile":
        if not schema or not table or not column:
            msg = "quantile classification requires schema, table, and column args"
            raise ValueError(msg)
        breaks = _quantile_breaks(schema, table, column, num_classes)

    elif method == "logarithmic":
        breaks = _logarithmic_breaks(
            stats.min_value or 0,
            stats.max_value or 0,
            num_classes,
        )

    elif method == "std_deviation":
        breaks = _std_deviation_breaks(
            stats.mean or 0,
            stats.stddev or 1,
            num_classes,
        )

    elif method == "manual":
        breaks = manual_breaks or [stats.min_value or 0, stats.max_value or 0]

    else:
        msg = f"Unknown classification method: {method}"
        raise ValueError(msg)

    labels = _make_labels(breaks)

    return ClassificationResult(
        method=method,
        breaks=breaks,
        labels=labels,
    )

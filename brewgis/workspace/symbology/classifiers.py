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
    """Build human-readable labels from break points.

    Adjacent breaks that round to the same text are re-rendered at full
    precision: a clustering method places boundaries inside dense runs of
    values, where neighbouring breaks can be arbitrarily close, and a class
    must never be labelled as an empty range like ``"528.34 - 528.34"``.
    """
    formatted = [_fmt(value) for value in breaks]
    for index in range(len(breaks) - 1):
        if formatted[index] == formatted[index + 1]:
            formatted[index] = repr(float(breaks[index]))
            formatted[index + 1] = repr(float(breaks[index + 1]))
    return [f"{formatted[i]} - {formatted[i + 1]}" for i in range(len(breaks) - 1)]


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


def _dedupe_adjacent(breaks: list[float]) -> list[float]:
    """Collapse runs of identical adjacent break values into one."""
    cleaned = [breaks[0]]
    for b in breaks[1:]:
        if b != cleaned[-1]:
            cleaned.append(b)
    return cleaned


def _quantile_tile_edges(
    schema: str,
    table: str,
    column: str,
    num_classes: int,
    *,
    distinct: bool = False,
    exclude_zero: bool = False,
) -> list[float]:
    """Break points from the min/max of each NTILE bucket, deduplicated.

    ``distinct=True`` buckets the column's distinct values instead of its
    rows — the tie-tolerant fallback ``_quantile_breaks`` falls back to.
    ``exclude_zero`` leaves zero values out, for a symbology that draws them
    as transparent.
    """
    qualifier = "DISTINCT " if distinct else ""
    included = " AND val <> 0" if exclude_zero else ""
    sql = f"""
        WITH values_ AS (
            SELECT {qualifier}"{column}"::double precision AS val
            FROM "{schema}"."{table}"
        ),
        ranked AS (
            SELECT val, NTILE({num_classes}) OVER (ORDER BY val) AS tile
            FROM values_
            WHERE val IS NOT NULL{included}
        )
        SELECT MIN(val), MAX(val), tile
        FROM ranked
        GROUP BY tile
        ORDER BY tile
    """  # noqa: S608 -- identifiers are catalog-sourced, never user input
    with connection.cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()

    if not rows:
        return [0.0]

    breaks = [rows[0][0]]
    for _, max_v, _ in rows[:-1]:
        breaks.append(max_v)
    breaks.append(rows[-1][1])
    return _dedupe_adjacent(breaks)


def _quantile_breaks(
    schema: str,
    table: str,
    column: str,
    num_classes: int,
    *,
    exclude_zero: bool = False,
) -> list[float]:
    """NTILE-based quantile classification using a single SQL query.

    NTILE splits by row count, so a column with heavy ties — a zero-inflated
    analysis result like VMT, where most features share the value 0 — puts
    several tile boundaries on that one value. Deduplicating them then leaves
    far fewer classes than requested (a single one, when the ties span the
    leading tiles), which renders the layer as one flat color. When that
    happens the boundaries are recomputed over the column's *distinct* values
    instead, so they spread across the values that actually occur rather than
    letting one tied value consume several tiles.

    ``exclude_zero`` drops zero values from both passes, for a symbology that
    draws them as transparent.
    """
    if num_classes < 1:
        included = f' AND "{column}" <> 0' if exclude_zero else ""
        sql = f"""
            SELECT MIN("{column}")::double precision
            FROM "{schema}"."{table}"
            WHERE "{column}" IS NOT NULL{included}
        """  # noqa: S608 -- identifiers are catalog-sourced, never user input
        with connection.cursor() as cursor:
            cursor.execute(sql)
            (min_val,) = cursor.fetchone()
        return [min_val]

    breaks = _quantile_tile_edges(
        schema, table, column, num_classes, exclude_zero=exclude_zero
    )
    if len(breaks) - 1 < num_classes:
        distinct_breaks = _quantile_tile_edges(
            schema,
            table,
            column,
            num_classes,
            distinct=True,
            exclude_zero=exclude_zero,
        )
        if len(distinct_breaks) > len(breaks):
            return distinct_breaks
    return breaks


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


_NATURAL_BREAKS_BUCKETS = 300
"""Rank buckets the natural-breaks sample is drawn from.

Each bucket contributes one weighted point to the optimisation — a real value
plus the number of rows it stands for — so the classifier sees the shape of
the distribution without loading the column. Buckets are cut by rank over the
column's *distinct* values, so the budget is spent on values that actually
occur: a zero-inflated column merges its whole zero mass into a single point
instead of consuming most of the buckets, and the rest goes to the values
that vary.
"""


def _natural_breaks_points(
    schema: str,
    table: str,
    column: str,
    buckets: int = _NATURAL_BREAKS_BUCKETS,
    *,
    exclude_zero: bool = False,
) -> list[tuple[float, float]]:
    """Sample *column* into at most *buckets* weighted points, low to high.

    Each point is ``(value, weight)``: the smallest value in its bucket, and
    the number of rows that value range holds. Points therefore sit on real
    values, and the last one is the column's largest value, so the top class
    closes on the data's maximum rather than stopping short of it.

    ``exclude_zero`` samples the non-zero values only, for a symbology that
    draws zero as transparent — the zeros' weight would otherwise anchor one
    of the classes on a value the map never shows.
    """
    included = f' AND "{column}" <> 0' if exclude_zero else ""
    sql = f"""
        WITH distinct_values AS (
            SELECT "{column}"::double precision AS val, COUNT(*) AS row_count
            FROM "{schema}"."{table}"
            WHERE "{column}" IS NOT NULL{included}
            GROUP BY 1
        ),
        numbered AS (
            SELECT val, row_count, NTILE({buckets}) OVER (ORDER BY val) AS tile
            FROM distinct_values
        )
        SELECT MIN(val), MAX(val), SUM(row_count)::bigint
        FROM numbered
        GROUP BY tile
        ORDER BY tile
    """  # noqa: S608 -- identifiers are catalog-sourced, never user input
    with connection.cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()

    last = len(rows) - 1
    return [
        (
            float(max_val) if index == last else float(min_val),
            float(weight),
        )
        for index, (min_val, max_val, weight) in enumerate(rows)
    ]


def _merge_equal_points(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Collapse consecutive points that share a value into one weighted point.

    A boundary between two identical values is no boundary at all, so a run of
    one tied value has to reach the optimisation as a single point.
    """
    merged: list[tuple[float, float]] = []
    for value, weight in points:
        if merged and merged[-1][0] == value:
            merged[-1] = (value, merged[-1][1] + weight)
            continue
        merged.append((value, weight))
    return merged


def _lower_bounds_from_dp(
    values: list[float], lower: list[list[int]], num_classes: int
) -> list[float]:
    """Turn the DP's class starts back into break values, lowest first.

    ``lower[classes][end]`` is the point *before* that class, so the class's
    own lower bound is the point after it — except for the first class, which
    starts at the first point. The largest value closes the top class.
    """
    breaks = [values[-1]]
    end = len(values)
    for classes in range(num_classes, 0, -1):
        start = lower[classes][end]
        breaks.append(values[0] if classes == 1 else values[start])
        end = start
    breaks.reverse()
    return breaks


def _weighted_natural_breaks(
    points: list[tuple[float, float]], num_classes: int
) -> list[float]:
    """Jenks natural breaks over weighted points.

    Minimises the within-class sum of squared deviations, each point counting
    as *weight* rows rather than once — so a value half the column takes part
    in carries its share of the distribution, and the search can't wander off
    into the sparse tail. The result is a strictly increasing subset of the
    points' own values: one boundary per class, and no boundary ever landing
    inside a run of identical values (which is what collapsed a heavily tied
    column into a single class before).

    Prefix sums make each candidate segment's cost constant time, giving
    O(num_classes x len(points)^2) — the old formulation rescanned every
    segment, O(num_classes x len(points)^3).
    """
    values = [value for value, _weight in points]
    if num_classes < 1 or not points:
        return values[:1] or [0.0]

    points = _merge_equal_points(points)
    values = [value for value, _weight in points]

    if len(points) <= num_classes:
        # Fewer values than classes: each value gets its own class.
        return values

    # Scale for numeric headroom: squared deviations over a million-row column
    # of millions-scale values rounded badly in float64 when left unscaled.
    scale = max(abs(value) for value in values) or 1.0
    prefix_weight = [0.0]
    prefix_sum = [0.0]
    prefix_squares = [0.0]
    for value, weight in points:
        scaled = value / scale
        prefix_weight.append(prefix_weight[-1] + weight)
        prefix_sum.append(prefix_sum[-1] + weight * scaled)
        prefix_squares.append(prefix_squares[-1] + weight * scaled * scaled)

    count = len(points)

    def class_cost(low: int, high: int) -> float:
        """Squared deviations of the points ``low..high`` (1-based, inclusive)."""
        weight = prefix_weight[high] - prefix_weight[low - 1]
        if weight <= 0:
            return 0.0
        total = prefix_sum[high] - prefix_sum[low - 1]
        squares = prefix_squares[high] - prefix_squares[low - 1]
        return max(squares - total * total / weight, 0.0)

    # lower[classes][end] — where the last of *classes* classes starts, and
    # variance[classes][end] — the cost of that optimal partition.
    lower = [[0] * (count + 1) for _ in range(num_classes + 1)]
    variance = [[0.0] * (count + 1) for _ in range(num_classes + 1)]
    for classes in range(1, num_classes + 1):
        lower[classes][1] = 1
    for end in range(2, count + 1):
        variance[1][end] = class_cost(1, end)
    for classes in range(2, num_classes + 1):
        for end in range(2, count + 1):
            best = math.inf
            # The top class always spans at least two points (when there are
            # enough): a class holding nothing but the largest value has no
            # width to label — its own lower bound *is* the maximum — so it
            # would render as an unreachable duplicate of the step above it,
            # wasting one of the requested classes.
            last_split = (
                end - 2 if (classes == num_classes and end == count) else end - 1
            )
            for split in range(lower[classes - 1][end - 1], last_split + 1):
                candidate = variance[classes - 1][split] + class_cost(split + 1, end)
                if candidate < best:
                    best = candidate
                    lower[classes][end] = split
            variance[classes][end] = best

    return _lower_bounds_from_dp(values, lower, num_classes)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify(
    stats: Any,
    method: str = "quantile",
    num_classes: int = 5,
    schema: str | None = None,
    table: str | None = None,
    column: str | None = None,
    manual_breaks: list[float] | None = None,
    *,
    exclude_zero: bool = False,
) -> ClassificationResult:
    """Classify a column into *num_classes* bins using *method*.

    Parameters
    ----------
    stats:
        A ``ColumnStatistics`` instance (or compatible duck-type with
        ``min_value``, ``max_value``, ``mean``, ``stddev`` and ``count``
        attributes).
    method:
        One of ``"natural_breaks"``, ``"jenks"``, ``"equal_interval"``,
        ``"quantile"``, ``"logarithmic"``, ``"std_deviation"``, or
        ``"manual"``.
    num_classes:
        Number of output classes.
    schema, table, column:
        Required for the methods that read the column's own distribution
        (``"quantile"`` and ``"natural_breaks"``).
    manual_breaks:
        Break points (n+1 values) when *method* is ``"manual"``.
    exclude_zero:
        Classify the non-zero values only — what a symbology with "Zero
        Transparent" draws. Applies to the methods that read the column
        directly (``"quantile"``, ``"natural_breaks"``); the methods that work
        from *stats* inherit it from how those statistics were computed (see
        ``stats.compute_statistics``).

    Returns
    -------
    ClassificationResult
    """
    breaks: list[float]

    if method in ("natural_breaks", "jenks"):
        if not schema or not table or not column:
            msg = (
                "natural breaks classification requires schema, table, and column args"
            )
            raise ValueError(msg)
        breaks = _weighted_natural_breaks(
            _natural_breaks_points(schema, table, column, exclude_zero=exclude_zero),
            num_classes,
        )

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
        breaks = _quantile_breaks(
            schema, table, column, num_classes, exclude_zero=exclude_zero
        )

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

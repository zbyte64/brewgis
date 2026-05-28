"""Hypothesis strategies for generating synthetic dbt model input data.

Each strategy mirrors the shape and range of columns that a dbt model
receives from its upstream ref().  Values are bounded to physically
meaningful ranges — no negative dwelling units, no infinite areas.
"""
# ruff: noqa: ANN201
# mypy: ignore-errors

from __future__ import annotations

from hypothesis import strategies as st

# ── Array strategies ─────────────────────────────────────────────────


def float_array(
    min_size: int = 1,
    max_size: int = 10,
    min_value: float = 0.0,
    max_value: float = 1e6,
) -> st.SearchStrategy:
    """Strategy for a ``np.ndarray`` of floats in a plausible domain."""
    return st.lists(
        st.floats(
            min_value=min_value,
            max_value=max_value,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=min_size,
        max_size=max_size,
    ).map(lambda lst: __import__("numpy", fromlist=[""]).array(lst, dtype=float))


def nullable_float_array(
    min_size: int = 1,
    max_size: int = 10,
    min_value: float = 0.0,
    max_value: float = 1e6,
) -> st.SearchStrategy:
    """Float array where some entries may be NaN (simulating SQL NULLs after COALESCE becomes 0)."""
    return st.lists(
        st.one_of(
            st.floats(
                min_value=min_value,
                max_value=max_value,
                allow_nan=False,
                allow_infinity=False,
            ),
            st.floats(min_value=-1.0, max_value=-1.0),  # sentinel: will be replaced
        ),
        min_size=min_size,
        max_size=max_size,
    ).map(
        lambda lst: __import__("numpy", fromlist=[""]).array(
            [0.0 if v < 0 else v for v in lst], dtype=float
        )
    )


def _np(lst):
    import numpy as np

    return np.array(lst, dtype=float)


def float_array_pair(
    min_value_1=0.0,
    max_value_1=1e6,
    min_value_2=0.0,
    max_value_2=1e6,
    min_size=1,
    max_size=50,
):
    """Two float arrays of the same (random) length."""
    return st.integers(min_value=min_size, max_value=max_size).flatmap(
        lambda n: st.tuples(
            st.lists(
                st.floats(
                    min_value=min_value_1,
                    max_value=max_value_1,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                min_size=n,
                max_size=n,
            ).map(_np),
            st.lists(
                st.floats(
                    min_value=min_value_2,
                    max_value=max_value_2,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                min_size=n,
                max_size=n,
            ).map(_np),
        )
    )


def float_array_triple(
    min_value_1=0.0,
    max_value_1=1e6,
    min_value_2=0.0,
    max_value_2=1e6,
    min_value_3=0.0,
    max_value_3=1e6,
    min_size=1,
    max_size=50,
):
    """Three float arrays of the same (random) length."""
    return st.integers(min_value=min_size, max_value=max_size).flatmap(
        lambda n: st.tuples(
            st.lists(
                st.floats(
                    min_value=min_value_1,
                    max_value=max_value_1,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                min_size=n,
                max_size=n,
            ).map(_np),
            st.lists(
                st.floats(
                    min_value=min_value_2,
                    max_value=max_value_2,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                min_size=n,
                max_size=n,
            ).map(_np),
            st.lists(
                st.floats(
                    min_value=min_value_3,
                    max_value=max_value_3,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                min_size=n,
                max_size=n,
            ).map(_np),
        )
    )


# ── Named strategies matching common dbt column patterns ──────────────

DWELLING_UNITS = float_array(min_value=0, max_value=5000, max_size=50)
POPULATION = float_array(min_value=0, max_value=15000, max_size=50)
HOUSEHOLDS = float_array(min_value=0, max_value=5000, max_size=50)
EMPLOYMENT_TOTAL = float_array(min_value=0, max_value=10000, max_size=50)
BUILDING_SQFT = float_array(min_value=0, max_value=5e6, max_size=50)
ACRES = float_array(min_value=0, max_value=100, max_size=50)
TRIPS = float_array(min_value=0, max_value=50000, max_size=50)

RATES = st.floats(min_value=0.0, max_value=1.0)
PERCENTAGES = st.floats(min_value=0.0, max_value=100.0)
POSITIVE_FLOATS = st.floats(
    min_value=1e-6, max_value=1e6, allow_nan=False, allow_infinity=False
)

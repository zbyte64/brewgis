"""Contract between the DU regressor's training ratios and its inference scaling.

The DU model predicts dwelling units per square foot of Overture building area,
so the trainer's denominator and the inference model's multiplier are one
contract split across two modules. When the multiplier is not a column the
streaming query selects — or the two sides drift onto different denominators —
the failure is an ``UndefinedColumn`` or ``KeyError`` part-way through a
multi-hour plan, which is how the per-subtype ``replace("du_", "bldg_sqft_")``
mapping failed.
"""

from __future__ import annotations

import pandas as pd

from brewgis.sqlmesh.models.base_canvas.du_inference import _base_query
from brewgis.sqlmesh.models.python.parcel_du_regressor import DU_RATIO_DENOMINATOR
from brewgis.sqlmesh.models.python.parcel_du_regressor import DU_TARGETS
from brewgis.sqlmesh.models.python.parcel_du_regressor import _fetch_du_training_data


class _SqlCapturingContext:
    """Execution context stand-in that records the trainer's query."""

    def __init__(self) -> None:
        self.sql = ""

    @staticmethod
    def resolve_table(name: str) -> str:
        return name

    def fetchdf(self, sql: str) -> pd.DataFrame:
        self.sql = sql
        return pd.DataFrame()


class TestDuRatioContract:
    def test_trainer_divides_every_target_by_the_observed_footprint(self) -> None:
        context = _SqlCapturingContext()
        _fetch_du_training_data(context)  # type: ignore[arg-type]

        for target in DU_TARGETS:
            expected = (
                f"COALESCE(ref.{target} / NULLIF(bs.{DU_RATIO_DENOMINATOR}, 0), 0)"
                f" AS {target}"
            )
            assert expected in context.sql, (
                f"{target} is not per {DU_RATIO_DENOMINATOR}"
            )

    def test_inference_query_selects_the_column_it_scales_by(self) -> None:
        query = _base_query("some_schema.parcel_dasymetric_weights")

        assert (
            f"COALESCE(dw.{DU_RATIO_DENOMINATOR}, 0) AS {DU_RATIO_DENOMINATOR}" in query
        )

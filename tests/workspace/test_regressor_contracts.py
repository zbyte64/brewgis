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

from brewgis.sqlmesh.models.base_canvas.du_inference import _base_query
from brewgis.sqlmesh.models.python.parcel_du_regressor import DU_RATIO_DENOMINATOR


class TestDuRatioContract:
    def test_inference_query_selects_the_column_it_scales_by(self) -> None:
        query = _base_query("some_schema.parcel_dasymetric_weights")

        assert (
            f"COALESCE(dw.{DU_RATIO_DENOMINATOR}, 0) AS {DU_RATIO_DENOMINATOR}" in query
        )

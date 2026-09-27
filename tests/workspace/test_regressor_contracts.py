"""Cross-module contract between the DU and SQFT regressors.

The DU model predicts dwelling units per square foot of building stock, so its
targets and their denominators are one contract split across two halves: the
trainer divides the reference dwelling units by the stock, and the region
inference model multiplies the predicted ratio back by it. Name drift between
the two halves surfaces as an ``UndefinedColumn`` or ``KeyError`` part-way
through a multi-hour plan, which is how the duplicated ``replace("du_",
"bldg_sqft_")`` mapping failed.
"""

from __future__ import annotations

from brewgis.sqlmesh.models.python.parcel_du_regressor import DU_TARGET_SQFT
from brewgis.sqlmesh.models.python.parcel_du_regressor import DU_TARGETS
from brewgis.sqlmesh.models.python.parcel_sqft_regressor import SQFT_TARGETS


class TestDuSqftContract:
    def test_every_du_target_has_a_denominator(self) -> None:
        """A DU target the trainer cannot express per square foot cannot be trained."""
        assert set(DU_TARGETS) == set(DU_TARGET_SQFT)

    def test_denominators_are_building_stock_the_sqft_model_predicts(self) -> None:
        """Denominators must be per-type ``bldg_sqft_*`` that exist at serving time.

        The region building adapters carry only the 4-way split
        (residential/commercial/industrial/other), so ``sqft_inference`` is the
        only per-type building area available, and it emits exactly
        ``SQFT_TARGETS``.
        """
        missing = set(DU_TARGET_SQFT.values()) - set(SQFT_TARGETS)
        assert not missing, f"no per-type building area for {sorted(missing)}"

    def test_multi_family_subtypes_share_the_mf_stock(self) -> None:
        """The reference splits multi-family dwelling units but not MF building area."""
        assert DU_TARGET_SQFT["du_mf2to4"] == "bldg_sqft_mf"
        assert DU_TARGET_SQFT["du_mf5p"] == "bldg_sqft_mf"

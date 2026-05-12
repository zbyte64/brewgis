"""Calibration registry — per-category calibration parameters for base canvas ETL.

Provides named presets (SACOG, national default) with a merge helper for
on-the-fly overrides.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field


@dataclass(frozen=True)
class CategoryCalibration:
    """Calibration parameters for one land-development category."""

    sqft_per_du: float = 1200.0
    sqft_per_emp: float = 300.0
    irrigation_res_frac: float = 0.1
    irrigation_com_frac: float = 0.05
    intersection_density: float = 12.5


@dataclass(frozen=True)
class CalibrationPreset:
    """Named calibration preset for a metropolitan region / geography type."""

    name: str
    description: str
    categories: dict[str, CategoryCalibration] = field(default_factory=dict)
    source_reference: str = ""

    def get(self, category: str) -> CategoryCalibration:
        """Return calibration for *category*, falling back to defaults."""
        return self.categories.get(category, CategoryCalibration())


# ── Presets ──────────────────────────────────────────────────────────

SACOG_CALIBRATION = CalibrationPreset(
    name="sacog",
    description="SACOG Sacramento Area Council of Governments — calibrated against v1 reference",
    source_reference="planning/urbanfootprint-sacog-source-db.sql.gz (2008–2012 base year)",
    categories={
        "urban": CategoryCalibration(
            sqft_per_du=1200.0,
            sqft_per_emp=400.0,
            irrigation_res_frac=0.25,
            irrigation_com_frac=0.035,
            intersection_density=25.0,
        ),
        "agricultural": CategoryCalibration(
            sqft_per_du=1200.0,
            sqft_per_emp=300.0,
            irrigation_res_frac=0.34,
            irrigation_com_frac=0.029,
            intersection_density=2.0,
        ),
        "industrial": CategoryCalibration(
            sqft_per_du=1200.0,
            sqft_per_emp=500.0,
            irrigation_res_frac=0.25,
            irrigation_com_frac=0.035,
            intersection_density=8.0,
        ),
        "undeveloped": CategoryCalibration(
            sqft_per_du=0.0,
            sqft_per_emp=0.0,
            irrigation_res_frac=0.0,
            irrigation_com_frac=0.0,
            intersection_density=1.0,
        ),
        "mixed_use": CategoryCalibration(
            sqft_per_du=1500.0,
            sqft_per_emp=400.0,
            irrigation_res_frac=0.25,
            irrigation_com_frac=0.035,
            intersection_density=20.0,
        ),
    },
)


NATIONAL_DEFAULT = CalibrationPreset(
    name="national_default",
    description="National default values — no region-specific calibration available",
    categories={},
)


def merge_presets(
    base: CalibrationPreset, overrides: CalibrationPreset
) -> CalibrationPreset:
    """Merge two presets: overrides take precedence per-category, per-field."""
    merged_categories = dict(base.categories)
    for cat_name, cat_cal in overrides.categories.items():
        existing = merged_categories.get(cat_name, CategoryCalibration())
        merged_categories[cat_name] = CategoryCalibration(
            sqft_per_du=cat_cal.sqft_per_du
            if cat_cal.sqft_per_du != 1200
            else existing.sqft_per_du,
            sqft_per_emp=cat_cal.sqft_per_emp
            if cat_cal.sqft_per_emp != 300
            else existing.sqft_per_emp,
            irrigation_res_frac=(
                cat_cal.irrigation_res_frac
                if cat_cal.irrigation_res_frac != 0.1
                else existing.irrigation_res_frac
            ),
            irrigation_com_frac=(
                cat_cal.irrigation_com_frac
                if cat_cal.irrigation_com_frac != 0.05
                else existing.irrigation_com_frac
            ),
            intersection_density=(
                cat_cal.intersection_density
                if cat_cal.intersection_density != 12.5
                else existing.intersection_density
            ),
        )
    return CalibrationPreset(
        name=f"{base.name}+{overrides.name}",
        description=f"Merged: {base.description} with overrides from {overrides.description}",
        source_reference=f"{base.source_reference}; {overrides.source_reference}",
        categories=merged_categories,
    )

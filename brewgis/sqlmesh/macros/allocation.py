from __future__ import annotations

import json

from sqlmesh import macro


@macro()
def compute_applied_acres(
    evaluator, developable_acres: str, dev_pct: str, gross_net_pct: str
) -> str:
    """Compute density-adjusted acres.

    applied_acres = developable_acres * dev_pct / 100.0 * gross_net_pct / 100.0

    Args:
        developable_acres: Developable acreage (after constraints).
        dev_pct: Percent of developable area to develop.
        gross_net_pct: Gross-to-net acreage ratio.

    Returns:
        SQL expression for density-adjusted acres.
    """
    return f"({developable_acres}) * ({dev_pct}) / 100.0 * ({gross_net_pct}) / 100.0"


@macro()
def compute_dwelling_units(evaluator, acres: str, du_per_acre: str) -> str:
    """Compute dwelling units from density-adjusted acres and a density rate.

    dwelling_units = density_adjusted_acres * du_per_acre

    Args:
        acres: Density-adjusted acreage.
        du_per_acre: Dwelling units per acre.

    Returns:
        SQL expression for dwelling units.
    """
    return f"({acres}) * ({du_per_acre})"


@macro()
def compute_population(evaluator, du: str, household_size: str) -> str:
    """Compute population from dwelling units.

    population = dwelling_units * household_size

    Args:
        du: Dwelling units (integer expression).
        household_size: Average persons per household.

    Returns:
        SQL expression for population.
    """
    return f"({du}) * ({household_size})"


@macro()
def compute_households(evaluator, du: str, vacancy_rate: str) -> str:
    """Compute households from dwelling units.

    households = dwelling_units * (1 - vacancy_rate / 100.0)

    Args:
        du: Dwelling units (integer expression).
        vacancy_rate: Vacancy rate (percent).

    Returns:
        SQL expression for households.
    """
    return f"({du}) * (1.0 - ({vacancy_rate}) / 100.0)"


@macro()
def compute_employment(evaluator, acres: str, emp_per_acre: str) -> str:
    """Compute employment from density-adjusted acres.

    employment = density_adjusted_acres * emp_per_acre

    Args:
        acres: Density-adjusted acreage.
        emp_per_acre: Employment per acre.

    Returns:
        SQL expression for employment.
    """
    return f"({acres}) * ({emp_per_acre})"


@macro()
def compute_floor_area(evaluator, acres: str, far: str) -> str:
    """Compute floor area (sqft) from density-adjusted acres.

    floor_area_sqft = density_adjusted_acres * 43560 * far

    Args:
        acres: Density-adjusted acreage.
        far: Floor area ratio.

    Returns:
        SQL expression for floor area in square feet.
    """
    return f"({acres}) * 43560.0 * ({far})"


@macro()
def classify_land_dev_category(
    evaluator,
    du_per_acre: str,
    urban_threshold: str = "10.0",
    compact_threshold: str = "5.0",
    standard_threshold: str = "1.0",
) -> str:
    """Classify land development category based on dwelling unit density.

    Classification:
        Urban:       du_per_acre >= urban_threshold
        Compact:     du_per_acre >= compact_threshold
        Standard:    du_per_acre >= standard_threshold
        Rural:       du_per_acre < standard_threshold

    Default thresholds:
        urban_threshold: 10.0
        compact_threshold: 5.0
        standard_threshold: 1.0

    Args:
        du_per_acre: Dwelling units per acre expression.
        urban_threshold: Density threshold for urban classification.
        compact_threshold: Density threshold for compact classification.
        standard_threshold: Density threshold for standard classification.

    Returns:
        SQL CASE expression for land development category.
    """
    return f"""CASE
    WHEN {du_per_acre} >= {urban_threshold} THEN 'urban'
    WHEN {du_per_acre} >= {compact_threshold} THEN 'compact'
    WHEN {du_per_acre} >= {standard_threshold} THEN 'standard'
    ELSE 'rural'
END"""


@macro()
def distribute_employment(evaluator, total_emp_expr: str, sector_mix) -> str:
    """Distribute total employment across sectors using a sector mix dict.

    The sector_mix is a Python dict: {"retail": 0.3, "office": 0.4, "industrial": 0.3}
    or a JSON string: ``'{"retail": 0.3, "office": 0.4, "industrial": 0.3}'`` when
    called from SQL model files.

    Returns a comma-separated list of SQL expressions for use in a SELECT clause.

    Args:
        total_emp_expr: SQL expression for total employment.
        sector_mix: Dict mapping sector names to fraction of total employment,
            or a JSON string representation.

    Returns:
        Comma-separated SQL expressions producing per-sector employment columns.
    """
    if isinstance(sector_mix, str):
        sector_mix = json.loads(sector_mix)
    parts = []
    for sector, fraction in sector_mix.items():
        parts.append(f"({total_emp_expr}) * {fraction} AS employment_{sector}")
    return ",\n        ".join(parts)

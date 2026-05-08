"""SACOG v1 → BaseCanvasSchema column mapping.

Maps columns from the v1 ``elk_grove_base_canvas`` table to the v3
``BaseCanvasSchema`` 77-column specification.

Most columns map 1:1 with only prefix differences:
  - ``acres_*`` → ``area_*``           (v1 used "acres" prefix, v3 uses "area")
  - ``bldg_sqft_*`` → ``bldg_area_*``  (v1 used "bldg_sqft", v3 uses "bldg_area")
  - ``intersection_density_sqmi`` → ``intersection_density``

Units note: v1 ``residential_irrigated_sqft`` / ``commercial_irrigated_sqft``
are in square feet; v3 ``residential_irrigated_area`` / ``commercial_irrigated_area``
are in acres. The mapping handles the /43560 conversion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# v1 source table that serves as the base for mapping
V1_BASE_TABLE = "public.elk_grove_base_canvas"

# Columns that exist in v1 but have no BaseCanvasSchema equivalent (kept for reference)
V1_EXTRA_COLUMNS = frozenset({
    "geography_id",
    "source_id",
    "region_lu_code",
    "sqft_parcel",
    "acres_parcel",
    "developable_proportion",
    "dev_pct",
    "density_pct",
    "gross_net_pct",
    "dirty_flag",
    "jurisdiction",
    "county",
    "clear_flag",
    "created",
    "updated",
})


@dataclass(frozen=True)
class ColumnMapping:
    """A single column mapping from v1 → v3."""

    # The v1 column name in elk_grove_base_canvas
    v1_column: str

    # The v3 BaseCanvasSchema column name (if applicable)
    v3_column: str | None

    # SQL expression to transform the v1 value (None for simple passthrough)
    sql_expr: str | None = None

    # Whether this column's data comes from the v1 FlatBuiltForm key
    from_built_form: bool = False

    # Default value if v1 column is missing
    default: float | str | None = 0.0


# ── Column Mapping Definitions ──────────────────────────────────────

IDENTITY_MAPPINGS = [
    ColumnMapping(v1_column="geography_id", v3_column="id", sql_expr="ROW_NUMBER() OVER (ORDER BY geography_id)", default=None),
    ColumnMapping(v1_column="geography_id", v3_column="id_source", sql_expr="'sacog_v1'", default=None),
    ColumnMapping(v1_column="source_id", v3_column="geometry_key", sql_expr="source_id || '@sacog'"),
    ColumnMapping(v1_column="wkb_geometry", v3_column="geometry", sql_expr="wkb_geometry"),
    ColumnMapping(v1_column="land_development_category", v3_column="land_development_category"),
    ColumnMapping(v1_column="built_form_key", v3_column="built_form_key"),
]

AREA_MAPPINGS = [
    # acres_* → area_*
    ColumnMapping("acres_gross", "area_gross"),
    ColumnMapping("acres_parcel", "area_parcel"),
    ColumnMapping("residential_irrigated_sqft", "residential_irrigated_area", sql_expr="residential_irrigated_sqft / 43560.0"),
    ColumnMapping("commercial_irrigated_sqft", "commercial_irrigated_area", sql_expr="commercial_irrigated_sqft / 43560.0"),
    ColumnMapping("acres_parcel_res_detsf", "area_parcel_res_detsf"),
    ColumnMapping("acres_parcel_res_detsf_sl", "area_parcel_res_detsf_sl"),
    ColumnMapping("acres_parcel_res_detsf_ll", "area_parcel_res_detsf_ll"),
    ColumnMapping("acres_parcel_res_attsf", "area_parcel_res_attsf"),
    ColumnMapping("acres_parcel_res_mf", "area_parcel_res_mf"),
    ColumnMapping("acres_parcel_res", "area_parcel_res"),
    ColumnMapping("acres_parcel_emp", "area_parcel_emp"),
    ColumnMapping("acres_parcel_emp_ret", "area_parcel_emp_ret"),
    ColumnMapping("acres_parcel_emp_off", "area_parcel_emp_off"),
    ColumnMapping("acres_parcel_emp_pub", "area_parcel_emp_pub"),
    ColumnMapping("acres_parcel_emp_ind", "area_parcel_emp_ind"),
    ColumnMapping("acres_parcel_emp_ag", "area_parcel_emp_ag"),
    ColumnMapping("acres_parcel_emp_military", "area_parcel_emp_military"),
    ColumnMapping("acres_parcel_mixed_use", "area_parcel_mixed_use"),
    ColumnMapping("acres_parcel_no_use", "area_parcel_no_use"),
]

DEMOGRAPHIC_MAPPINGS = [
    ColumnMapping("intersection_density_sqmi", "intersection_density"),
    ColumnMapping("pop", "pop"),
    ColumnMapping("hh", "hh"),
    ColumnMapping("du", "du"),
    ColumnMapping("du_detsf", "du_detsf"),
    ColumnMapping("du_detsf_sl", "du_detsf_sl"),
    ColumnMapping("du_detsf_ll", "du_detsf_ll"),
    ColumnMapping("du_attsf", "du_attsf"),
    ColumnMapping("du_mf", "du_mf"),
    ColumnMapping("du_mf2to4", "du_mf2to4"),
    ColumnMapping("du_mf5p", "du_mf5p"),
]

EMPLOYMENT_MAPPINGS = [
    ColumnMapping("emp", "emp"),
    ColumnMapping("emp_ret", "emp_ret"),
    ColumnMapping("emp_retail_services", "emp_retail_services"),
    ColumnMapping("emp_restaurant", "emp_restaurant"),
    ColumnMapping("emp_accommodation", "emp_accommodation"),
    ColumnMapping("emp_arts_entertainment", "emp_arts_entertainment"),
    ColumnMapping("emp_other_services", "emp_other_services"),
    ColumnMapping("emp_off", "emp_off"),
    ColumnMapping("emp_office_services", "emp_office_services"),
    ColumnMapping("emp_medical_services", "emp_medical_services"),
    ColumnMapping("emp_pub", "emp_pub"),
    ColumnMapping("emp_public_admin", "emp_public_admin"),
    ColumnMapping("emp_education", "emp_education"),
    ColumnMapping("emp_ind", "emp_ind"),
    ColumnMapping("emp_manufacturing", "emp_manufacturing"),
    ColumnMapping("emp_wholesale", "emp_wholesale"),
    ColumnMapping("emp_transport_warehousing", "emp_transport_warehousing"),
    ColumnMapping("emp_utilities", "emp_utilities"),
    ColumnMapping("emp_construction", "emp_construction"),
    ColumnMapping("emp_ag", "emp_ag"),
    ColumnMapping("emp_agriculture", "emp_agriculture"),
    ColumnMapping("emp_extraction", "emp_extraction"),
    ColumnMapping("emp_military", "emp_military"),
]

BUILDING_AREA_MAPPINGS = [
    # bldg_sqft_* → bldg_area_*
    ColumnMapping("bldg_sqft_detsf_sl", "bldg_area_detsf_sl"),
    ColumnMapping("bldg_sqft_detsf_ll", "bldg_area_detsf_ll"),
    ColumnMapping("bldg_sqft_attsf", "bldg_area_attsf"),
    ColumnMapping("bldg_sqft_mf", "bldg_area_mf"),
    ColumnMapping("bldg_sqft_retail_services", "bldg_area_retail_services"),
    ColumnMapping("bldg_sqft_restaurant", "bldg_area_restaurant"),
    ColumnMapping("bldg_sqft_accommodation", "bldg_area_accommodation"),
    ColumnMapping("bldg_sqft_arts_entertainment", "bldg_area_arts_entertainment"),
    ColumnMapping("bldg_sqft_other_services", "bldg_area_other_services"),
    ColumnMapping("bldg_sqft_office_services", "bldg_area_office_services"),
    ColumnMapping("bldg_sqft_public_admin", "bldg_area_public_admin"),
    ColumnMapping("bldg_sqft_education", "bldg_area_education"),
    ColumnMapping("bldg_sqft_medical_services", "bldg_area_medical_services"),
    ColumnMapping("bldg_sqft_transport_warehousing", "bldg_area_transport_warehousing"),
    ColumnMapping("bldg_sqft_wholesale", "bldg_area_wholesale"),
]

# Columns NOT present in v1 that need imputation defaults
MISSING_COLUMNS = [
    # Area — no v1 equivalents for these
    ColumnMapping(v1_column=None, v3_column="area_dev_condition", default=0.0),  # type: ignore[arg-type]
    ColumnMapping(v1_column=None, v3_column="area_row", default=0.0),  # type: ignore[arg-type]
    # Demographics
    ColumnMapping(v1_column=None, v3_column="pop_groupquarter", default=0.0),  # type: ignore[arg-type]
]

# All mappings combined, in BaseCanvasSchema column order
ALL_MAPPINGS: list[ColumnMapping] = (
    IDENTITY_MAPPINGS + AREA_MAPPINGS + DEMOGRAPHIC_MAPPINGS + EMPLOYMENT_MAPPINGS + BUILDING_AREA_MAPPINGS + MISSING_COLUMNS
)

# Fast lookup: v3_column → ColumnMapping
V3_TO_MAPPING: dict[str, ColumnMapping] = {m.v3_column: m for m in ALL_MAPPINGS if m.v3_column}


def get_mapping(v3_column: str) -> ColumnMapping | None:
    """Return the ColumnMapping for a BaseCanvasSchema column name."""
    return V3_TO_MAPPING.get(v3_column)


def v1_columns_present() -> list[str]:
    """Return list of v1 column names that successfully map to BaseCanvasSchema."""
    return [m.v1_column for m in ALL_MAPPINGS if m.v1_column and m.v1_column != "geography_id"]


def build_create_view_sql(
    schema: str,
    view_name: str,
    v1_table: str = V1_BASE_TABLE,
    built_form_table: str = "public.footprint_flatbuiltform",
    order_by: str = "geography_id",
) -> str:
    """Generate CREATE OR REPLACE VIEW SQL mapping v1 columns to BaseCanvasSchema.

    Builds a view that renames v1 columns to v3 names, handles unit conversions,
    and provides defaults for missing columns.
    """
    select_parts: list[str] = []

    # Ordered list of BaseCanvasSchema column names
    from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

    for v3_col in BaseCanvasSchema.COLUMN_NAMES:
        mapping = V3_TO_MAPPING.get(v3_col)
        if mapping is None:
            # No mapping defined — use COALESCE with default
            col_def = BaseCanvasSchema.get(v3_col)
            default = col_def.default_value if col_def else 0.0
            select_parts.append(f"CAST({default!r} AS DOUBLE PRECISION) AS {v3_col}")
        elif mapping.sql_expr:
            # Custom SQL expression
            select_parts.append(f"{mapping.sql_expr} AS {v3_col}")
        elif mapping.default is not None and mapping.v1_column is None:
            # Hard-coded default for missing column
            if isinstance(mapping.default, str):
                select_parts.append(f"CAST({mapping.default!r} AS DOUBLE PRECISION) AS {v3_col}")
            else:
                select_parts.append(f"CAST({mapping.default!r} AS DOUBLE PRECISION) AS {v3_col}")
        elif mapping.v1_column:
            # Direct passthrough
            select_parts.append(f"{mapping.v1_column} AS {v3_col}")
        else:
            select_parts.append(f"CAST(0.0 AS DOUBLE PRECISION) AS {v3_col}")

    select_clause = ",\n    ".join(select_parts)
    q_view = f'"{schema}"."{view_name}"'
    q_table = v1_table

    return f"""CREATE OR REPLACE VIEW {q_view} AS
SELECT
    {select_clause}
FROM {q_table};
"""


def get_v1_columns_for_verification() -> dict[str, str]:
    """Return ``{v3_column: v1_column}`` for columns that have a direct v1 counterpart.

    Used by the imputation validator to compare imputed vs. original.
    """
    result: dict[str, str] = {}
    for mapping in ALL_MAPPINGS:
        if mapping.v1_column and mapping.v3_column and mapping.v1_column not in ("geography_id", "source_id", "wkb_geometry"):
            result[mapping.v3_column] = mapping.v1_column
    return result

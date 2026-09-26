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
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brewgis.workspace.services.base_canvas_schema import ColumnDef

logger = logging.getLogger(__name__)

# v1 source table that serves as the base for mapping
V1_BASE_TABLE = "public.elk_grove_base_canvas"

# Columns that exist in v1 but have no BaseCanvasSchema equivalent (kept for reference)
V1_EXTRA_COLUMNS = frozenset(
    {
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
    }
)


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
    ColumnMapping(
        v1_column="geography_id",
        v3_column="parcel_id",
        sql_expr="ROW_NUMBER() OVER (ORDER BY geography_id)",
        default=None,
    ),
    ColumnMapping(
        v1_column="geography_id",
        v3_column="id_source",
        sql_expr="'sacog_v1'",
        default=None,
    ),
    ColumnMapping(
        v1_column="source_id",
        v3_column="geometry_key",
        sql_expr="source_id || '@sacog'",
    ),
    ColumnMapping(
        v1_column="wkb_geometry", v3_column="geometry", sql_expr="wkb_geometry"
    ),
    ColumnMapping(
        v1_column="land_development_category", v3_column="land_development_category"
    ),
    ColumnMapping(v1_column="built_form_key", v3_column="built_form_key"),
]

AREA_MAPPINGS = [
    # acres_* → area_*
    ColumnMapping("acres_gross", "area_gross"),
    ColumnMapping("acres_parcel", "area_parcel"),
    ColumnMapping(
        "residential_irrigated_sqft",
        "residential_irrigated_area",
        sql_expr="residential_irrigated_sqft / 43560.0",
    ),
    ColumnMapping(
        "commercial_irrigated_sqft",
        "commercial_irrigated_area",
        sql_expr="commercial_irrigated_sqft / 43560.0",
    ),
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
    IDENTITY_MAPPINGS
    + AREA_MAPPINGS
    + DEMOGRAPHIC_MAPPINGS
    + EMPLOYMENT_MAPPINGS
    + BUILDING_AREA_MAPPINGS
    + MISSING_COLUMNS
)

# Fast lookup: v3_column → ColumnMapping
V3_TO_MAPPING: dict[str, ColumnMapping] = {
    m.v3_column: m for m in ALL_MAPPINGS if m.v3_column
}


def get_mapping(v3_column: str) -> ColumnMapping | None:
    """Return the ColumnMapping for a BaseCanvasSchema column name."""
    return V3_TO_MAPPING.get(v3_column)


def v1_columns_present() -> list[str]:
    """Return list of v1 column names that successfully map to BaseCanvasSchema."""
    return [
        m.v1_column
        for m in ALL_MAPPINGS
        if m.v1_column and m.v1_column != "geography_id"
    ]


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


# Columns whose values must come from the source's own parcel identity rather
# than from ``ALL_MAPPINGS``. ``build_create_view_sql`` numbers ``parcel_id``
# with ``ROW_NUMBER()`` and passes ``wkb_geometry`` through in its source CRS,
# which is enough for a view the demo workspace only reads through; a table a
# workspace *adopts* has to carry the source parcel key itself — the convention
# the comparison pipeline states as "SACOG source uses geography_id; SQLMesh
# models expect parcel_id" (``management/commands/compare_sacog_basemap.py``) —
# and the geometry every canvas view, tile server and model expects.
SOURCE_IDENTITY_SQL: dict[str, str] = {
    "parcel_id": "geography_id",
    "geography_id": "geography_id",
    "geometry": "ST_Multi(ST_Transform(wkb_geometry, {srid}))",
}


def _quote(identifier: str) -> str:
    """Double-quote an identifier, refusing anything that is not a plain name."""
    if not identifier.replace("_", "").isalnum():
        msg = f"Refusing to quote unexpected identifier: {identifier!r}"
        raise ValueError(msg)
    return f'"{identifier}"'


def _default_literal(col: ColumnDef) -> str:
    """Render a column's declared default as a SQL literal of its own type."""
    value = col.default_value
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, (int, float)):
        return repr(float(value))
    # No default declared (or Django's NOT_PROVIDED sentinel): an empty string
    # for a text column, otherwise the zero the imputation pass would write.
    return (
        "''" if col.pg_type.upper().startswith(("VARCHAR", "TEXT", "CHAR")) else "0.0"
    )


def _typed_expression(
    v3_col: str, col: ColumnDef, *, srid: int, fill_nulls: bool
) -> str:
    """Return the source expression for *v3_col*.

    *col* supplies the declared default for a column v1 has no counterpart for
    and the value used to fill a NULL in an expression that reads the source,
    *srid* the CRS the base canvas contract mandates, *fill_nulls* whether such a
    NULL must be filled — true only for a column that is NOT NULL in the
    contract, the same values ``import_sacog_demo --step stitch`` coalesces.
    """
    override = SOURCE_IDENTITY_SQL.get(v3_col)
    if override is not None:
        # Never filled: a source parcel without a key or a geometry is not a
        # base canvas row, and inventing one would corrupt the canvas silently.
        return override.format(srid=srid)
    mapping = V3_TO_MAPPING.get(v3_col)
    if mapping is not None and mapping.sql_expr:
        expression = mapping.sql_expr
    elif mapping is not None and mapping.v1_column:
        expression = _quote(mapping.v1_column)
    else:
        # No v1 counterpart (land_use, assessor_use_code, the equity
        # percentages): the schema's own default. Nothing to fill.
        return _default_literal(col)
    if fill_nulls:
        return f"COALESCE({expression}, {_default_literal(col)})"
    return expression


def build_materialized_select_sql(v1_table: str = V1_BASE_TABLE) -> str:
    """Generate the ``SELECT`` mapping a v1-shaped table onto ``BaseCanvasSchema``.

    Unlike ``build_create_view_sql`` — which feeds a view read only through the
    workspace — every column here is cast to the type the base canvas contract
    declares, so the statement can be handed straight to
    ``INSERT INTO <base canvas table> (…)``: an untransformed geometry, a
    ``ROW_NUMBER()`` key or a float default on a ``VARCHAR`` column would all be
    wrong in a table whose typmods are part of the contract. A NULL in a NOT NULL
    column is filled with that column's declared default — most of them are counts
    the ETL pipeline's imputation pass zeroes anyway — except the parcel key and
    the geometry, which fail the insert instead.

    Returns a ``SELECT`` (no trailing semicolon) over *v1_table*, with one
    output column per ``BaseCanvasSchema.COLUMN_NAMES`` entry, in that order.
    """
    from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

    select_parts: list[str] = []
    for v3_col in BaseCanvasSchema.COLUMN_NAMES:
        col = BaseCanvasSchema.get(v3_col)
        if col is None:
            continue
        pg_type = (
            BaseCanvasSchema.GEOMETRY_TYPE if v3_col == "geometry" else col.pg_type
        )
        expression = _typed_expression(
            v3_col,
            col,
            srid=BaseCanvasSchema.GEOMETRY_SRID,
            fill_nulls=v3_col in BaseCanvasSchema.NON_NULL_COLUMNS,
        )
        select_parts.append(f"    CAST({expression} AS {pg_type}) AS {_quote(v3_col)}")
    return "SELECT\n" + ",\n".join(select_parts) + f"\nFROM {v1_table}"


def get_v1_columns_for_verification() -> dict[str, str]:
    """Return ``{v3_column: v1_column}`` for columns that have a direct v1 counterpart.

    Used by the imputation validator to compare imputed vs. original.
    """
    result: dict[str, str] = {}
    for mapping in ALL_MAPPINGS:
        if (
            mapping.v1_column
            and mapping.v3_column
            and mapping.v1_column not in ("geography_id", "source_id", "wkb_geometry")
        ):
            result[mapping.v3_column] = mapping.v1_column
    return result

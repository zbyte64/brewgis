"""Region assessor sales adapter — Python SQL model (blueprinted).

One row per APN with the best available sales observation (dedup logic runs
once here instead of in 3+ consumer models).

- SACOG: deduplicates ``brewgis.staging.sacog_assessor_sales_raw``.
- Fresno: no assessor sales — produces zero rows (consumers LEFT JOIN and
  fall back to regressor estimates).

The branch is driven by the ``source_table`` blueprint variable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from sqlglot import exp
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

if TYPE_CHECKING:
    from sqlmesh.core.macros import MacroEvaluator

SACOG_QUERY = """
SELECT
    apn,
    living_area AS actual_living_sqft,
    building_sf AS actual_building_sqft,
    property_type,
    lot_size_acres AS sales_lot_size_acres,
    units
FROM (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY apn
            ORDER BY
                CASE
                    WHEN living_area IS NOT NULL AND building_sf IS NOT NULL AND units IS NOT NULL THEN 0
                    WHEN living_area IS NOT NULL THEN 1
                    WHEN building_sf IS NOT NULL THEN 2
                    ELSE 3
                END,
                year_built DESC NULLS LAST
        ) AS rn
    FROM {source_table}
    WHERE living_area IS NOT NULL OR building_sf IS NOT NULL
) dedup
WHERE rn = 1;
"""

EMPTY_QUERY = """
SELECT
    NULL::text AS apn,
    NULL::double precision AS actual_living_sqft,
    NULL::double precision AS actual_building_sqft,
    NULL::text AS property_type,
    NULL::double precision AS sales_lot_size_acres,
    NULL::integer AS units
FROM (SELECT 1) t
WHERE FALSE;
"""


@model(
    "brewgis.@{region}.assessor_sales_deduped",
    kind={"name": ModelKindName.FULL},
    columns={
        "apn": "text",
        "actual_living_sqft": "double",
        "actual_building_sqft": "double",
        "property_type": "text",
        "sales_lot_size_acres": "double",
        "units": "int",
    },
    audits=[
        ("not_null", {"columns": [exp.to_column("apn")]}),
        ("unique_values", {"columns": [exp.to_column("apn")]}),
    ],
    depends_on=[
        "@IF(@source_table != '', brewgis.staging.sacog_assessor_sales_raw, brewgis.@{region}.parcel_shim)",
    ],
    post_statements=[
        "CREATE INDEX IF NOT EXISTS idx_@{region}_assessor_sales_deduped_apn_@snapshot_hash ON @this_model USING btree (apn)",
        "ANALYZE @this_model",
    ],
    blueprints=[
        {"region": "sacog", "source_table": "brewgis.staging.sacog_assessor_sales_raw"},
        {"region": "fresno", "source_table": ""},
    ],
    is_sql=True,
)
def execute(evaluator: MacroEvaluator, **kwargs: Any) -> str:
    """Return dedup SQL for SACOG, empty result for regions without sales data."""
    source_table = evaluator.blueprint_var("source_table", "")
    if source_table:
        return SACOG_QUERY.format(source_table=source_table)
    return EMPTY_QUERY

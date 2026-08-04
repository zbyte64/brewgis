"""Region parcel sales features adapter — Python SQL model (blueprinted).

Materializes the ``known`` parcels for the k-NN footprint imputation cascade:
parcels with both Overture building footprint features AND assessor sales
records.

- SACOG: joins ``brewgis.staging.sacog_assessor_sales_raw`` (the known set).
- Fresno: no assessor sales — zero rows, so the imputation tiers find no
  neighbors and ``@{region}.parcel_footprint_imputed`` emits no rows (the
  authoritative-residential-area chain falls back to Overture footprints).

The branch is driven by the ``sales_raw_table`` blueprint variable.
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
WITH latest_block_groups AS (
    SELECT DISTINCT ON (apn) *
    FROM brewgis.{region}.parcel_block_groups
    ORDER BY apn, data_year DESC
)
SELECT DISTINCT ON (pbf.apn)
    pbf.apn,
    pbf.geometry,
    pbf.footprint_ratio,
    pbf.building_count,
    pbf.lot_size_acres,
    pbf.land_development_category,
    pbg.block_group_geoid,
    pbg.tract_geoid,
    s.property_type,
    COALESCE(s.units, 1) AS units,
    s.living_area AS living_sqft,
    s.building_sf AS building_sqft
FROM brewgis.{region}.parcel_building_footprints pbf
JOIN latest_block_groups pbg ON pbf.apn = pbg.apn
JOIN {sales_raw_table} s ON pbf.apn = s.apn
WHERE pbf.footprint_ratio > 0
  AND s.property_type IS NOT NULL
  AND s.property_type != '';
"""

EMPTY_QUERY = """
SELECT
    NULL::text AS apn,
    NULL::geometry AS geometry,
    NULL::double precision AS footprint_ratio,
    NULL::integer AS building_count,
    NULL::double precision AS lot_size_acres,
    NULL::text AS land_development_category,
    NULL::text AS block_group_geoid,
    NULL::text AS tract_geoid,
    NULL::text AS property_type,
    NULL::integer AS units,
    NULL::double precision AS living_sqft,
    NULL::double precision AS building_sqft
FROM (SELECT 1) t
WHERE FALSE;
"""


@model(
    "brewgis.@{region}.parcel_sales_features",
    kind={"name": ModelKindName.FULL},
    columns={
        "apn": "text",
        "geometry": "geometry",
        "footprint_ratio": "double",
        "building_count": "int",
        "lot_size_acres": "double",
        "land_development_category": "text",
        "block_group_geoid": "text",
        "tract_geoid": "text",
        "property_type": "text",
        "units": "int",
        "living_sqft": "double",
        "building_sqft": "double",
    },
    audits=[
        ("not_null", {"columns": [exp.to_column("apn")]}),
        ("unique_values", {"columns": [exp.to_column("apn")]}),
    ],
    depends_on=[
        "brewgis.@{region}.parcel_building_footprints",
        "brewgis.@{region}.parcel_block_groups",
        "@IF(@sales_raw_table != '', brewgis.staging.sacog_assessor_sales_raw, brewgis.@{region}.parcel_shim)",
    ],
    post_statements=[
        "CREATE INDEX IF NOT EXISTS idx_@{region}_parcel_sales_features_geometry_@snapshot_hash ON @this_model USING GIST (geometry)",
        "CREATE INDEX IF NOT EXISTS idx_@{region}_parcel_sales_features_apn_@snapshot_hash ON @this_model USING btree (apn)",
        "CREATE INDEX IF NOT EXISTS idx_@{region}_parcel_sales_features_bg_ldc_@snapshot_hash ON @this_model USING btree (block_group_geoid, land_development_category)",
        "CREATE INDEX IF NOT EXISTS idx_@{region}_parcel_sales_features_tract_ldc_@snapshot_hash ON @this_model USING btree (tract_geoid, land_development_category)",
        "CREATE INDEX IF NOT EXISTS idx_@{region}_parcel_sales_features_ldc_@snapshot_hash ON @this_model USING btree (land_development_category)",
        "ANALYZE @this_model",
    ],
    blueprints=[
        {
            "region": "sacog",
            "sales_raw_table": "brewgis.staging.sacog_assessor_sales_raw",
        },
        {"region": "fresno", "sales_raw_table": ""},
    ],
    is_sql=True,
)
def execute(evaluator: MacroEvaluator, **kwargs: Any) -> str:
    """Return the SACOG known-parcels SQL or an empty result for regions without sales."""
    region = evaluator.blueprint_var("region")
    sales_raw_table = evaluator.blueprint_var("sales_raw_table", "")
    if sales_raw_table:
        return SACOG_QUERY.format(region=region, sales_raw_table=sales_raw_table)
    return EMPTY_QUERY

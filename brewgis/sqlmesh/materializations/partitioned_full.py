from __future__ import annotations

import typing as t

from sqlmesh import CustomMaterialization
from sqlmesh import Model

if t.TYPE_CHECKING:
    from sqlmesh import QueryOrDF

_DEFAULT_PARTITION_VALUES: tuple[str, ...] = (
    "urban",
    "compact",
    "standard",
    "rural",
    "agricultural",
    "industrial",
    "undeveloped",
    "mixed_use",
)

_sentinel = object()


class PartitionedFullMaterialization(CustomMaterialization):
    """Custom materialization that creates a PostgreSQL LIST-partitioned table.

    DDL is generated from the model's ``columns_to_types`` to produce
    ``CREATE TABLE ... PARTITION BY LIST (<partition_col>)``.  One child
    partition is created per configured value, plus a DEFAULT partition to
    catch any new values that appear after the partition set is defined.

    ``insert()`` delegates to ``replace_query()`` — PG routing sends each
    row to the correct partition automatically.

    SQLMesh config properties:

    ``partition_by`` (default ``land_development_category``)
        Column to partition on.  Must exist in the model's columns.

    ``partition_values`` (default all 8 land-development categories)
        Explicit list of partition-key values to create child partitions
        for.  If omitted, the default set covers the categories derived
        from the ``assessor_use_codes`` seed.
    """

    NAME = "partitioned_full"

    def _partition_col(self, model: Model) -> str:
        return model.custom_materialization_properties.get(
            "partition_by", "land_development_category"
        )

    def _partition_values(self, model: Model) -> list[str]:
        vals = model.custom_materialization_properties.get(
            "partition_values", _sentinel
        )
        if vals is _sentinel:
            return list(_DEFAULT_PARTITION_VALUES)
        return list(vals)

    def create(
        self,
        table_name: str,
        model: Model,
        is_table_deployable: bool,  # noqa: FBT001, ARG002
        render_kwargs: dict[str, t.Any],  # noqa: ARG002
        skip_grants: bool,  # noqa: FBT001, ARG002
        **kwargs: t.Any,  # noqa: ARG002
    ) -> None:
        from brewgis.sqlmesh.utils import sqlglot_to_pg_type

        cols = getattr(model, "columns_to_types", None)
        if not cols:
            cols = getattr(model, "columns_to_types_", None)
        if not cols:
            msg = (
                f"Model {model.name} has no columns_to_types — "
                "cannot generate CREATE TABLE DDL"
            )
            raise ValueError(msg)

        partition_col = self._partition_col(model)
        partition_values = self._partition_values(model)

        col_defs = [
            f'"{cname}" {sqlglot_to_pg_type(str(ctype), str(cname))}'
            for cname, ctype in cols.items()
        ]

        ddl = (
            f"CREATE TABLE IF NOT EXISTS {table_name} (\n"
            f"    {', '.join(col_defs)}\n"
            f") PARTITION BY LIST ({partition_col})"
        )
        self.adapter.execute(ddl)

        for value in partition_values:
            safe_value = str(value).replace("'", "").replace('"', "")
            part_name = f"{table_name}__{safe_value}"
            self.adapter.execute(
                f"CREATE TABLE IF NOT EXISTS {part_name}"
                f" PARTITION OF {table_name}"
                f" FOR VALUES IN ('{safe_value}')"
            )

        default_name = f"{table_name}__default"
        self.adapter.execute(
            f"CREATE TABLE IF NOT EXISTS {default_name}"
            f" PARTITION OF {table_name} DEFAULT"
        )

    def insert(
        self,
        table_name: str,
        query_or_df: QueryOrDF,
        model: Model,  # noqa: ARG002
        is_first_insert: bool,  # noqa: FBT001, ARG002
        render_kwargs: dict[str, t.Any],  # noqa: ARG002
        **kwargs: t.Any,  # noqa: ARG002
    ) -> None:
        self.adapter.replace_query(table_name, query_or_df)

    def delete(self, name: str, **kwargs: t.Any) -> None:  # noqa: ARG002
        self.adapter.execute(f"DROP TABLE IF EXISTS {name} CASCADE")

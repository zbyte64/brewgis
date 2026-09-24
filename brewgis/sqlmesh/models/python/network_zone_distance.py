"""Network zone distance — per-scenario road-network zone-to-zone matrix.

One instance per analyzed scenario (``brewgis.ascn<scenario_pk>``), blueprinted
like :mod:`brewgis.sqlmesh.models.python.trip_distribution`. When the scenario
sets ``transport_use_network_distance`` it holds the shortest drivable path, in
km, between every connected pair of 2 km grid zones its parcels fall in, routed
by ``pgr_dijkstraCost`` over the region's ``road_network_vertices`` /
``road_network_edges``; trip_distribution feeds it to the gravity model. With the
option off it is empty and pgRouting is never called. With no analyzed scenario
there is nothing to instantiate, and the module registers no model at all (see
:mod:`brewgis.sqlmesh.blueprint_models`).

Zones rather than parcels: a parcel-to-parcel matrix is ~4.5e10 pairs for a
213k-parcel region (see :mod:`brewgis.sqlmesh.models.python._network_zones`).
Each zone routes from the network vertex nearest the mean centroid of its
parcels.

This model is deliberately not an analysis module (no selector, no result
table): it is never restated by an analysis run, so the matrix is computed once
and cached. Its inputs are the scenario's parcel source and the region network,
not core_end_state, so restating ``core`` does not cascade into it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any

import numpy as np
import pandas as pd
from sqlglot import exp
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.blueprint_models import register_blueprint_model
from brewgis.sqlmesh.macros.analysis_blueprints import analysis_blueprint_profiles
from brewgis.sqlmesh.macros.geometry import metres_per_unit
from brewgis.sqlmesh.macros.geometry import require_local_srid
from brewgis.sqlmesh.macros.region_blueprints import REGIONS
from brewgis.sqlmesh.models.python._network_zones import MAX_ZONES
from brewgis.sqlmesh.models.python._network_zones import ZONE_CELL_METRES

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike

# Resolved when SQLMesh imports this module (i.e. while loading the project) —
# one entry per analyzed scenario in the database at that moment.
_PROFILES = analysis_blueprint_profiles("network_zone_distance")

# Origin vertices per pgr_dijkstraCost call: each call reloads the edge table,
# so batches amortize that, while staying small enough to log progress.
_ORIGIN_BATCH = 100

_COLUMNS = {
    "origin_ix": "INT",
    "origin_iy": "INT",
    "dest_ix": "INT",
    "dest_iy": "INT",
    "network_distance_km": "float",
}


# One declaration, applied once per analyzed scenario below: with none in the
# database there is nothing to instantiate.
_NETWORK_ZONE_DISTANCE_MODEL = model(
    # The table is spelled out rather than ``@{model_table}``: SQLMesh registers
    # Python models by their unrendered name, which trip_distribution already
    # claims ("Duplicate name").
    name="brewgis.@{scenario_schema}.network_zone_distance",
    kind=ModelKindName.FULL,
    description=(
        "Road-network distance between the scenario's 2 km grid zones, routed over"
        " the region's drivable Overture graph; empty unless the scenario uses"
        " network distance for trip distribution."
    ),
    column_descriptions={
        "origin_ix": "Origin zone grid column: floor of x metres over the zone cell size.",
        "origin_iy": "Origin zone grid row: floor of y metres over the zone cell size.",
        "dest_ix": "Destination zone grid column, same grid as origin_ix.",
        "dest_iy": "Destination zone grid row, same grid as origin_iy.",
        "network_distance_km": (
            "Shortest undirected drivable path between the zones' nearest road"
            " vertices (km); 0 for zones sharing a vertex."
        ),
    },
    columns=_COLUMNS,
    blueprints=[dict(profile) for profile in _PROFILES],
    audits=[
        # An expression, not a string: see trip_distribution's audits.
        (
            "assert_column_non_negative",
            {"column_name": exp.column("network_distance_km")},
        ),
    ],
)


def execute(
    context: ExecutionContext,
    start: TimeLike,  # noqa: ARG001
    end: TimeLike,  # noqa: ARG001
    execution_time: TimeLike,  # noqa: ARG001
    **kwargs: Any,  # noqa: ARG001
) -> Iterator[pd.DataFrame]:
    """Route every zone pair of the scenario over the region road network.

    A generator: with the option off it yields nothing (an empty table).

    Every ``resolve_table`` call names its model with the blueprint variable
    inlined and runs unconditionally, whether or not the option is on — the
    parse-time dependency rule documented in trip_distribution's ``execute``.
    """
    parcels = context.resolve_table(f"{context.blueprint_var('parcel_table')}")
    vertices = context.resolve_table(
        f"brewgis.{context.blueprint_var('road_network_region')}.road_network_vertices"
    )
    edges = context.resolve_table(
        f"brewgis.{context.blueprint_var('road_network_region')}.road_network_edges"
    )

    if not context.blueprint_var("transport_use_network_distance"):
        # SQLMesh cannot insert an empty DataFrame; yielding nothing leaves the
        # table empty.
        return

    scenario_pk = context.blueprint_var("scenario_pk")
    if not context.blueprint_var("road_network_available"):
        msg = (
            f"transport_use_network_distance is enabled for scenario {scenario_pk}"
            " but its workspace base table is not in a region with an Overture"
            f" road network ({', '.join(REGIONS)})"
        )
        raise RuntimeError(msg)

    srid = require_local_srid(context)
    mpu = metres_per_unit(srid)
    # The centroid expression is trip_distribution's, so both sides put every
    # parcel in the same cell (``_network_zones.zone_indices``).
    zones = context.fetchdf(
        f"""
        WITH c AS (
            SELECT ST_Transform(ST_Centroid(geometry), {srid}) AS c
            FROM {parcels}
            WHERE geometry IS NOT NULL
        ),
        cells AS (
            SELECT
                FLOOR(ST_X(c) * {mpu!r} / {ZONE_CELL_METRES!r})::INT AS ix,
                FLOOR(ST_Y(c) * {mpu!r} / {ZONE_CELL_METRES!r})::INT AS iy,
                AVG(ST_X(c)) AS mx,
                AVG(ST_Y(c)) AS my
            FROM c
            GROUP BY 1, 2
        )
        SELECT cells.ix, cells.iy, v.id AS vertex_id
        FROM cells
        CROSS JOIN LATERAL (
            SELECT id FROM {vertices}
            ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(cells.mx, cells.my), {srid})
            LIMIT 1
        ) AS v
        """  # noqa: S608 — table names are SQLMesh-resolved identifiers
    )
    n_zones = len(zones)
    if n_zones == 0:
        msg = f"network_zone_distance: parcel table {parcels} has no parcel geometry to zone"
        raise RuntimeError(msg)
    if n_zones > MAX_ZONES:
        msg = (
            f"{n_zones} network zones exceed MAX_ZONES={MAX_ZONES}"
            f" at ZONE_CELL_METRES={ZONE_CELL_METRES}"
        )
        raise RuntimeError(msg)

    # pgRouting runs the edge query itself, as a string literal the catalog
    # rewrite (sqlmesh/config.py) cannot see into — so it names the table without
    # the logical ``brewgis`` catalog; the session is already in that database.
    edge_table = exp.to_table(edges, dialect="postgres")
    edge_ref = exp.table_(edge_table.name, db=edge_table.db, quoted=True).sql(
        "postgres"
    )
    edge_sql = f"SELECT id, source, target, cost_m AS cost FROM {edge_ref}"  # noqa: S608
    edge_sql = edge_sql.replace("'", "''")

    vertex_ids = np.unique(zones["vertex_id"].to_numpy(dtype=np.int64))
    all_ids = ",".join(str(int(v)) for v in vertex_ids)
    batches = [
        vertex_ids[i : i + _ORIGIN_BATCH]
        for i in range(0, len(vertex_ids), _ORIGIN_BATCH)
    ]
    logger = logging.getLogger(__name__)
    costs = []
    for number, batch in enumerate(batches, start=1):
        logger.info("network_zone_distance: batch %d/%d", number, len(batches))
        origins = ",".join(str(int(v)) for v in batch)
        costs.append(
            context.fetchdf(
                # Model-generated integer ids and a resolved table name only.
                f"SELECT start_vid, end_vid, agg_cost FROM pgr_dijkstraCost("  # noqa: S608
                f"'{edge_sql}', ARRAY[{origins}]::BIGINT[], ARRAY[{all_ids}]::BIGINT[],"
                " directed := false)"
            )
        )

    routed = pd.concat(costs, ignore_index=True)
    routed = routed[routed["start_vid"] != routed["end_vid"]]
    # Zones snapped to the same vertex are 0 apart.
    same_vertex = pd.DataFrame(
        {"start_vid": vertex_ids, "end_vid": vertex_ids, "agg_cost": 0.0}
    )
    vertex_pairs = pd.concat(
        [routed[["start_vid", "end_vid", "agg_cost"]], same_vertex], ignore_index=True
    ).astype({"start_vid": np.int64, "end_vid": np.int64, "agg_cost": float})

    zone_vertices = zones.astype(
        {"ix": np.int32, "iy": np.int32, "vertex_id": np.int64}
    )
    pairs = vertex_pairs.merge(
        zone_vertices.rename(
            columns={"ix": "origin_ix", "iy": "origin_iy", "vertex_id": "start_vid"}
        ),
        on="start_vid",
    ).merge(
        zone_vertices.rename(
            columns={"ix": "dest_ix", "iy": "dest_iy", "vertex_id": "end_vid"}
        ),
        on="end_vid",
    )
    # cost_m is metres, so agg_cost is too.
    pairs["network_distance_km"] = pairs["agg_cost"] / 1000.0
    yield pairs[list(_COLUMNS)].reset_index(drop=True)


# One model per analyzed scenario: with none analyzed, registering nothing is
# what keeps an empty blueprint list from becoming a phantom model.
execute = register_blueprint_model(_NETWORK_ZONE_DISTANCE_MODEL, execute, _PROFILES)

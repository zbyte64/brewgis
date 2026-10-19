from __future__ import annotations

from decimal import Decimal

import sqlglot
from sqlglot import exp
from sqlmesh import macro

# Region order — the order blueprint entries are emitted in.
REGIONS: tuple[str, ...] = ("sacog", "fresno")


def region_profiles() -> dict[str, dict[str, str | int | Decimal]]:
    """Per-region blueprint facts — the single source of truth.

    Values are typed and rendered to SQL literal text by ``_variable_sql``:
    ``str`` becomes a quoted string literal, ``int`` a bare integer, and
    ``Decimal`` an exact decimal. ``Decimal`` is required for the overture
    bounding boxes because a binary float cannot hold the trailing zero in
    ``36.60``, and blueprint values feed each model's data_hash.

    Returned from a function rather than held in a module-level constant
    because SQLMesh serializes module-level values into the macro's python_env
    with ``repr()`` and evaluates them standalone (``prepare_env`` -> bare
    ``eval(payload)``, no namespace), which cannot express a ``Decimal``.
    """
    return {
        "sacog": {
            "region": "sacog",
            "county_name": "Sacramento",
            "county_fips": "067,005,017,061",
            "acs_year": 2013,
            "bg_vintage": "2013",
            "lodes_year": 2008,
            "overture_bbox_min_x": Decimal("-121.87"),
            "overture_bbox_max_x": Decimal("-121.01"),
            "overture_bbox_min_y": Decimal("38.02"),
            "overture_bbox_max_y": Decimal("38.74"),
            "parcel_table": "brewgis.sacog.parcel_shim",
            "dasymetric_source": "brewgis.sacog.comparison_dasymetric",
            "source": 0,
            "source_schema": "public",
            "source_table": "sacog_comparison_parcels",
            "nlcd_parcel_source": "brewgis.public.sacog_comparison_parcels",
            "nlcd_parcel_srid": 3310,
            "nlcd_parcel_id": "parcel_id",
        },
        "fresno": {
            "region": "fresno",
            "county_name": "Fresno",
            "county_fips": "019",
            "acs_year": 2022,
            "bg_vintage": "2023",
            "lodes_year": 2021,
            "overture_bbox_min_x": Decimal("-119.95"),
            "overture_bbox_max_x": Decimal("-119.55"),
            "overture_bbox_min_y": Decimal("36.60"),
            "overture_bbox_max_y": Decimal("36.92"),
            "parcel_table": "brewgis.fresno.parcel_shim",
            "dasymetric_source": "brewgis.fresno.comparison_dasymetric",
            "source": "brewgis.fresno.parcels",
            "source_schema": "brewgis",
            "source_table": "fresno.parcels",
            "nlcd_parcel_source": "brewgis.fresno.parcels",
            "nlcd_parcel_srid": 4326,
            "nlcd_parcel_id": "parcel_id",
        },
    }


def analysis_region_profiles() -> dict[str, dict[str, str]]:
    """Per-analysis-region facts: the regions a workspace can be analyzed in.

    A workspace's analysis region is its base table's schema, and it must be one
    of these (``fetch_clone.workspace_region``; there is no default). Every
    region data pipeline in ``REGIONS`` is one — its workspaces analyze the base
    canvas the pipeline reconstructs from public data — and so is ``sacog_v1``,
    the SACOG base canvas imported from the UrbanFootprint v1 database snapshot
    (``import_sacog_demo`` / ``materialize_sacog_base_canvas`` load it into the
    ``sacog_v1`` schema). The two SACOG workspaces are compared to validate the
    reconstruction, so each is analyzed against its own data:

    - ``constraint_layers`` — the region's own ``brewgis.<region>.constraint_layers``
      model (public FEMA flood zones + NWI wetlands for a pipeline region, the
      snapshot's streams/wetlands/vernal pools for ``sacog_v1``);
    - ``trip_length_table`` — reference trip-length zones (``schema.table``),
      empty for the gravity fallback (``models/python/trip_lengths.py``). Only
      the snapshot ships them: SACSIM's zones, restored from the dump, which
      cover the whole SACOG region despite the table's Elk Grove name;
    - ``public_data_region`` — the pipeline region whose public-data models
      (OpenStreetMap food POIs, the Overture road network) cover this one. A
      pipeline region is its own; the snapshot has none of its own, so it reads
      the ``sacog`` fetches rather than fetching the same area twice.

    A function for the same reason as ``region_profiles``.
    """
    return {
        "sacog": {
            "trip_length_table": "",
            "public_data_region": "sacog",
        },
        "fresno": {
            "trip_length_table": "",
            "public_data_region": "fresno",
        },
        "sacog_v1": {
            "trip_length_table": "public.elk_grove_vmt_base_trip_lengths",
            "public_data_region": "sacog",
        },
    }


def _variable_sql(name: str, value: str | int | Decimal) -> str:
    """Render one blueprint variable as the SQL literal text it originally had."""
    if name == "region":
        return str(value)  # identifier, not a string literal
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)  # int / Decimal -> exact numeric literal text


@macro()
def region_blueprints(evaluator, *regions: exp.Expr) -> list[exp.Expr]:
    """One blueprint entry per region, built from ``region_profiles()``.

    ``@region_blueprints()`` emits every region in ``REGIONS``;
    ``@region_blueprints('fresno')`` only the regions named, for a source that
    does not fit every region (the Planning Database's 2020 block groups have no
    place in SACOG's historical reconstruction).

    Models reference only the variables they need (e.g. ``@{region}``); SQLMesh
    drops unreferenced blueprint variables, so emitting the full profile per
    region leaves each model's data_hash unchanged.

    The profiles are returned inside one enclosing tuple because SQLMesh only
    wraps a *multi-element* rendered list itself: with a single region, a bare
    list would be read as that region's individual variables, producing one
    model per variable instead of one per region (see
    ``analysis_blueprints.analysis_blueprints``).
    """
    profiles = region_profiles()
    selected = [r.name for r in regions] or list(REGIONS)
    unknown = sorted(set(selected) - set(REGIONS))
    if unknown:
        msg = f"region_blueprints: unknown region(s) {unknown}; known: {list(REGIONS)}"
        raise ValueError(msg)
    entries = [
        sqlglot.parse_one(
            "("
            + ", ".join(
                f"{name} := {_variable_sql(name, value)}"
                for name, value in profiles[region].items()
            )
            + ")",
            into=exp.Tuple,
        )
        for region in REGIONS
        if region in selected
    ]
    return [exp.Tuple(expressions=entries)]

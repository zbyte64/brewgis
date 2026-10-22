"""Workspace packages — a workspace's base layer, exported for another server to import.

A package is a zip archive::

    manifest.json                 what the package is (``PackageManifest``)
    base_canvas.parquet           required — the base layer, GeoParquet
    built_forms.json              required — the Building Type library
    constraint_layers.parquet     when the workspace's constraint layers are its own
    trip_length_zones.parquet     when the workspace has reference trip-length zones
    food_pois.parquet             export option — the workspace's food outlets
    road_subsegments.parquet      export option — the workspace's road network

Every geometry is EPSG:4326. The manifest lists each part by ``kind`` with its
checksum, row count and columns; a kind this server does not know is refused
rather than skipped, so a package from a newer server never imports with part of
it silently dropped. Scenarios, paints, symbology and paint constraints are
future kinds — the format has room for them and this server refuses them.

Importing a package makes a **new workspace** whose analysis reads only what
the package carried plus public data over its extent
(``sqlmesh/macros/workspace_blueprints.py``): its base canvas is the package's
(``wsp<pk>.base_canvas``), its constraint layers and trip-length zones are the
package's when it shipped them, and its food outlets and road network are the
package's or, when it shipped none, fetched over the extent the first time an
analysis needs them. ``attach_package`` is the same step for an existing
workspace — how the SACOG v1 snapshot workspace reads its packaged data.

The export reads PostGIS through DuckDB, which writes GeoParquet natively and
streams rather than holding a 500k-parcel table in memory; the import never
writes a table itself — the parts are files the workspace's SQLMesh models read.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import duckdb
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db import transaction
from django.utils import timezone

from brewgis.sqlmesh.macros.workspace_blueprints import PART_FILES
from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix
from brewgis.workspace.models import WORKSPACE_PACKAGES_DIR
from brewgis.workspace.models import ConstraintSource
from brewgis.workspace.models import PublicDataSource
from brewgis.workspace.models import TripLengthSource
from brewgis.workspace.models import Workspace
from brewgis.workspace.models import validate_projected_srid
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.sqlmesh_tables import _column_type_requirement
from brewgis.workspace.services.workspace_base import adopt_base_table
from brewgis.workspace.services.workspace_base import create_base_scenario
from brewgis.workspace.services.workspace_base import plan_fresh
from brewgis.workspace.services.workspace_extent import extent_bounds
from brewgis.workspace.services.workspace_extent import extent_polygon

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Sequence

FORMAT = "brewgis.workspace-package"
FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
# ``(xmin, ymin, xmax, ymax)``.
_BBOX_LENGTH = 4


class PackageError(ValueError):
    """The archive is not a workspace package this server can import."""


class PartKind(StrEnum):
    BASE_CANVAS = "base_canvas"
    BUILT_FORMS = "built_forms"
    CONSTRAINT_LAYERS = "constraint_layers"
    TRIP_LENGTH_ZONES = "trip_length_zones"
    FOOD_POIS = "food_pois"
    ROAD_SUBSEGMENTS = "road_subsegments"


#: The archive member each part lives at.
PART_PATHS: dict[PartKind, str] = {
    **{PartKind(kind): filename for kind, filename in PART_FILES.items()},
    PartKind.BUILT_FORMS: "built_forms.json",
}
REQUIRED_PARTS = frozenset({PartKind.BASE_CANVAS, PartKind.BUILT_FORMS})
#: Parts that are a workspace's public data, exported only on request.
PUBLIC_DATA_PARTS = frozenset({PartKind.FOOD_POIS, PartKind.ROAD_SUBSEGMENTS})

# The columns each GeoParquet part must carry beside its geometry: what the
# workspace input model reading it selects (``models/workspace_inputs/``).
_GEOMETRY_COLUMN: dict[PartKind, str] = {
    PartKind.BASE_CANVAS: "geometry",
    PartKind.CONSTRAINT_LAYERS: "geometry",
    PartKind.TRIP_LENGTH_ZONES: "geometry",
    PartKind.FOOD_POIS: "geometry",
    PartKind.ROAD_SUBSEGMENTS: "wgs84_geometry",
}
_TRIP_LENGTH_COLUMNS = (
    "productions_hbw",
    "productions_hbo",
    "productions_nhb",
    "attractions_hbw",
    "attractions_hbo",
    "attractions_nhb",
)
_PART_COLUMNS: dict[PartKind, tuple[str, ...]] = {
    PartKind.CONSTRAINT_LAYERS: ("layer", "discount_pct"),
    PartKind.TRIP_LENGTH_ZONES: _TRIP_LENGTH_COLUMNS,
    PartKind.FOOD_POIS: ("osm_id", "name", "shop", "amenity", "food_class"),
    PartKind.ROAD_SUBSEGMENTS: (
        "segment_id",
        "from_connector_id",
        "from_at",
        "to_connector_id",
        "to_at",
    ),
}

# Built-form fields that are row identity or bookkeeping, not library content.
_BUILT_FORM_SKIPPED_FIELDS = frozenset({"id", "workspace", "created_at", "updated_at"})

_DUCKDB_NUMERIC_TYPES = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "FLOAT",
    "DOUBLE",
    "DECIMAL",
)


# ── Manifest ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PackagePart:
    """One file of a package."""

    kind: PartKind
    path: str
    sha256: str
    rows: int
    #: ``(name, DuckDB type)`` of a GeoParquet part's columns; empty for JSON.
    columns: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "path": self.path,
            "sha256": self.sha256,
            "rows": self.rows,
            "columns": [{"name": name, "type": type_} for name, type_ in self.columns],
        }


@dataclass(frozen=True)
class PackageManifest:
    """What a package is: the exported workspace's settings and its parts."""

    name: str
    local_srid: int
    extent: tuple[float, float, float, float]
    center_lng: float
    center_lat: float
    zoom: float
    fill_built_form: bool
    parts: tuple[PackagePart, ...]
    created_at: str = field(default_factory=lambda: timezone.now().isoformat())
    format_version: int = FORMAT_VERSION

    def part(self, kind: PartKind) -> PackagePart | None:
        return next((part for part in self.parts if part.kind == kind), None)

    def has(self, kind: PartKind) -> bool:
        return self.part(kind) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "format_version": self.format_version,
            "created_at": self.created_at,
            "workspace": {
                "name": self.name,
                "center_lng": self.center_lng,
                "center_lat": self.center_lat,
                "zoom": self.zoom,
                "fill_built_form": self.fill_built_form,
            },
            "local_srid": self.local_srid,
            "extent": list(self.extent),
            "crs": "EPSG:4326",
            "parts": [part.to_dict() for part in self.parts],
        }

    @classmethod
    def from_dict(cls, data: object) -> PackageManifest:
        """Parse and validate a manifest; raise ``PackageError`` naming what is wrong."""
        if not isinstance(data, dict):
            msg = "The manifest is not a JSON object."
            raise PackageError(msg)
        if data.get("format") != FORMAT:
            msg = f"Not a workspace package: format is {data.get('format')!r}, expected {FORMAT!r}."
            raise PackageError(msg)
        version = data.get("format_version")
        if version != FORMAT_VERSION:
            msg = (
                f"Package format version {version!r} is not supported by this "
                f"server (it reads version {FORMAT_VERSION})."
            )
            raise PackageError(msg)
        try:
            workspace = data["workspace"]
            extent = tuple(float(value) for value in data["extent"])
            parts = tuple(_parse_part(part) for part in data["parts"])
            manifest = cls(
                name=str(workspace["name"]),
                local_srid=int(data["local_srid"]),
                extent=extent,  # type: ignore[arg-type]
                center_lng=float(workspace["center_lng"]),
                center_lat=float(workspace["center_lat"]),
                zoom=float(workspace["zoom"]),
                fill_built_form=bool(workspace["fill_built_form"]),
                parts=parts,
                created_at=str(data.get("created_at", "")),
                format_version=FORMAT_VERSION,
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, PackageError):
                raise
            msg = f"The manifest is malformed: {error!r}."
            raise PackageError(msg) from error
        manifest.validate()
        return manifest

    def validate(self) -> None:
        """Refuse a manifest this server cannot import, naming the reason."""
        if len(self.extent) != _BBOX_LENGTH or not (
            self.extent[0] < self.extent[2] and self.extent[1] < self.extent[3]
        ):
            msg = f"The manifest's extent {list(self.extent)} is not a bounding box."
            raise PackageError(msg)
        try:
            validate_projected_srid(self.local_srid)
        except ValidationError as error:
            msg = f"The package's local_srid {self.local_srid} is unusable: {error.messages[0]}"
            raise PackageError(msg) from error
        kinds = [part.kind for part in self.parts]
        if len(kinds) != len(set(kinds)):
            msg = "The manifest lists a part kind more than once."
            raise PackageError(msg)
        missing = sorted(kind.value for kind in REQUIRED_PARTS - set(kinds))
        if missing:
            msg = f"The package is missing its required part(s): {', '.join(missing)}."
            raise PackageError(msg)
        if self.has(PartKind.FOOD_POIS) != self.has(PartKind.ROAD_SUBSEGMENTS):
            msg = (
                "A package ships its public data whole: food_pois and "
                "road_subsegments come together or not at all."
            )
            raise PackageError(msg)
        for part in self.parts:
            _validate_part_columns(part)


def _parse_part(data: dict[str, Any]) -> PackagePart:
    try:
        kind = PartKind(data["kind"])
    except ValueError as error:
        msg = (
            f"The package carries a part this server does not know: {data['kind']!r} "
            f"(known: {', '.join(kind.value for kind in PartKind)}). It was written by "
            "a newer server; upgrade this one to import it."
        )
        raise PackageError(msg) from error
    path = str(data["path"])
    if path != PART_PATHS[kind]:
        msg = f"Part {kind.value} is at {path!r}; the format puts it at {PART_PATHS[kind]!r}."
        raise PackageError(msg)
    return PackagePart(
        kind=kind,
        path=path,
        sha256=str(data["sha256"]),
        rows=int(data["rows"]),
        columns=tuple(
            (str(column["name"]), str(column["type"]))
            for column in data.get("columns", [])
        ),
    )


def _type_satisfies(requirement: str, duckdb_type: str) -> bool:
    upper = duckdb_type.upper()
    if requirement == "geometry":
        return upper.startswith("GEOMETRY")
    if requirement == "text":
        return upper == "VARCHAR"
    if requirement == "numeric":
        return upper.startswith(_DUCKDB_NUMERIC_TYPES)
    return True


def _validate_part_columns(part: PackagePart) -> None:
    """Refuse a GeoParquet part missing a column its reader needs, or at the wrong type."""
    if part.kind == PartKind.BUILT_FORMS:
        return
    types = dict(part.columns)
    geometry = _GEOMETRY_COLUMN[part.kind]
    if part.kind == PartKind.BASE_CANVAS:
        # This server's contract, not the exporting one's: every column the
        # canvas views, the paint surfaces and the analysis read.
        required = {
            name: _column_type_requirement(name)
            for name in BaseCanvasSchema.COLUMN_NAMES
        }
    else:
        required = dict.fromkeys(_PART_COLUMNS[part.kind], "any")
        required[geometry] = "geometry"
    missing = sorted(set(required) - set(types))
    if missing:
        msg = (
            f"Part {part.kind.value} lacks column(s) this server needs: "
            f"{', '.join(missing)}."
        )
        raise PackageError(msg)
    wrong = sorted(
        f"{name} ({types[name]}, needs {requirement})"
        for name, requirement in required.items()
        if not _type_satisfies(requirement, types[name])
    )
    if wrong:
        msg = f"Part {part.kind.value} has column(s) of the wrong type: {', '.join(wrong)}."
        raise PackageError(msg)


def read_manifest(archive: zipfile.ZipFile) -> PackageManifest:
    """The validated manifest of *archive*, every listed part present in it."""
    try:
        raw = archive.read(MANIFEST_NAME)
    except KeyError as error:
        msg = f"Not a workspace package: the archive has no {MANIFEST_NAME}."
        raise PackageError(msg) from error
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        msg = f"The manifest is not valid JSON: {error}."
        raise PackageError(msg) from error
    manifest = PackageManifest.from_dict(data)
    members = set(archive.namelist())
    absent = sorted(part.path for part in manifest.parts if part.path not in members)
    if absent:
        msg = f"The manifest lists part file(s) the archive does not hold: {', '.join(absent)}."
        raise PackageError(msg)
    return manifest


def open_package(path: Path) -> PackageManifest:
    """Validate the package at *path* without unpacking it."""
    try:
        with zipfile.ZipFile(path) as archive:
            return read_manifest(archive)
    except zipfile.BadZipFile as error:
        msg = f"Not a workspace package: {path.name} is not a zip archive."
        raise PackageError(msg) from error


# ── Export ────────────────────────────────────────────────────────────


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _qualified(table: str) -> str:
    schema, _, name = table.rpartition(".")
    return f"{_quote(schema or 'public')}.{_quote(name)}"


def _part_queries(
    workspace: Workspace, kinds: Iterable[PartKind]
) -> dict[PartKind, tuple[str, str]]:
    """``kind -> (PostGIS query, geometry column)`` for each GeoParquet part.

    Each query selects the part's columns plus its geometry as WKB in
    EPSG:4326 under the alias ``wkb``; DuckDB turns that back into its geometry.
    """
    schema = workspace.input_schema
    queries: dict[PartKind, tuple[str, str]] = {}
    for kind in kinds:
        if kind == PartKind.BASE_CANVAS:
            columns = [
                _quote(name)
                for name in BaseCanvasSchema.COLUMN_NAMES
                if name != "geometry"
            ]
            source = _qualified(workspace.base_table)
            geometry = "ST_Multi(ST_Transform(geometry, 4326))"
        elif kind == PartKind.CONSTRAINT_LAYERS:
            columns = [_quote(name) for name in _PART_COLUMNS[kind]]
            source = _qualified(f"{schema}.constraint_layers")
            geometry = "geom"
        elif kind == PartKind.TRIP_LENGTH_ZONES:
            columns = [_quote(name) for name in _PART_COLUMNS[kind]]
            source = _qualified(f"{schema}.trip_length_zones")
            geometry = "geometry"
        elif kind == PartKind.FOOD_POIS:
            columns = [_quote(name) for name in _PART_COLUMNS[kind]]
            source = _qualified(f"{schema}.food_pois")
            geometry = "geometry"
        elif kind == PartKind.ROAD_SUBSEGMENTS:
            columns = [_quote(name) for name in _PART_COLUMNS[kind]]
            source = _qualified(f"{schema}.road_subsegments")
            geometry = "wgs84_geometry"
        else:
            continue
        query = (
            f"SELECT {', '.join(columns)}, ST_AsBinary({geometry}) AS wkb FROM {source}"  # noqa: S608 — quoted identifiers
        )
        queries[kind] = (query, _GEOMETRY_COLUMN[kind])
    return queries


def _export_kinds(workspace: Workspace, *, include_public_data: bool) -> list[PartKind]:
    kinds = [PartKind.BASE_CANVAS]
    if workspace.constraint_source == ConstraintSource.PACKAGE:
        kinds.append(PartKind.CONSTRAINT_LAYERS)
    if workspace.trip_length_source == TripLengthSource.PACKAGE:
        kinds.append(PartKind.TRIP_LENGTH_ZONES)
    if include_public_data:
        kinds += [PartKind.FOOD_POIS, PartKind.ROAD_SUBSEGMENTS]
    return kinds


def _input_selectors(workspace: Workspace, kinds: Iterable[PartKind]) -> list[str]:
    """The workspace input models an export reads, so a plan can build them first."""
    schema = workspace.input_schema
    models = {
        PartKind.CONSTRAINT_LAYERS: "constraint_layers",
        PartKind.TRIP_LENGTH_ZONES: "trip_length_zones",
        PartKind.FOOD_POIS: "food_pois",
        PartKind.ROAD_SUBSEGMENTS: "road_subsegments",
    }
    return [f"+brewgis.{schema}.{models[kind]}" for kind in kinds if kind in models]


def _duckdb_with_postgres() -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB attached read-only to this server's database."""
    settings_dict = connection.settings_dict
    dsn = " ".join(
        f"{key}={value}"
        for key, value in (
            ("dbname", settings_dict["NAME"]),
            ("user", settings_dict["USER"]),
            ("password", settings_dict["PASSWORD"]),
            ("host", settings_dict["HOST"]),
            ("port", settings_dict["PORT"]),
        )
        if value
    )
    con = duckdb.connect()
    con.execute("LOAD spatial")
    con.execute("LOAD postgres")
    # ATTACH takes no bound parameters; the DSN is this server's own settings.
    con.execute(
        f"ATTACH '{dsn.replace(chr(39), chr(39) * 2)}' AS pg (TYPE postgres, READ_ONLY)"
    )
    return con


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_geoparquet(
    con: duckdb.DuckDBPyConnection,
    *,
    kind: PartKind,
    query: str,
    geometry: str,
    directory: Path,
) -> PackagePart:
    """Copy *query*'s rows into the part's GeoParquet file and describe it."""
    target = directory / PART_PATHS[kind]
    inner = query.replace("'", "''")
    selected = (
        f"SELECT * EXCLUDE (wkb), ST_GeomFromWKB(wkb) AS {_quote(geometry)} "  # noqa: S608 — project-built query, quoted identifiers
        f"FROM postgres_query('pg', '{inner}')"
    )
    # COPY's target cannot be a bound parameter; it is a path this function made.
    con.execute(f"COPY ({selected}) TO '{target}' (FORMAT parquet, COMPRESSION zstd)")
    columns = tuple(
        (str(row[0]), str(row[1]))
        for row in con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(target)]
        ).fetchall()
    )
    (rows,) = con.execute(
        "SELECT count(*) FROM read_parquet(?)", [str(target)]
    ).fetchone() or (0,)
    return PackagePart(
        kind=kind,
        path=PART_PATHS[kind],
        sha256=_sha256(target),
        rows=int(rows),
        columns=columns,
    )


def built_forms_document(workspace: Workspace) -> dict[str, list[dict[str, Any]]]:
    """The workspace's Building Type library as JSON-ready rows, keyed by name."""

    def fields_of(instance: Any) -> dict[str, Any]:
        return {
            model_field.name: model_field.value_from_object(instance)
            for model_field in type(instance)._meta.concrete_fields  # noqa: SLF001
            if model_field.name not in _BUILT_FORM_SKIPPED_FIELDS
        }

    return {
        "building_types": [
            fields_of(building_type)
            for building_type in BuildingType.objects.filter(
                workspace=workspace
            ).order_by("name")
        ],
        "place_types": [
            fields_of(place_type)
            for place_type in PlaceType.objects.filter(workspace=workspace).order_by(
                "name"
            )
        ],
        "mixes": [
            {
                "place_type": mix.place_type.name,
                "building_type": mix.building_type.name,
                "percentage": mix.percentage,
            }
            for mix in PlaceTypeBuildingTypeMix.objects.filter(
                place_type__workspace=workspace
            ).select_related("place_type", "building_type")
        ],
    }


def write_package(
    *,
    manifest_fields: dict[str, Any],
    parts: Sequence[PackagePart],
    directory: Path,
    destination: Path,
) -> Path:
    """Zip the part files in *directory* with their manifest into *destination*."""
    manifest = PackageManifest(parts=tuple(parts), **manifest_fields)
    manifest.validate()
    (directory / MANIFEST_NAME).write_text(json.dumps(manifest.to_dict(), indent=2))
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Parquet is already compressed; storing it keeps the export fast.
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.write(directory / MANIFEST_NAME, MANIFEST_NAME)
        for part in manifest.parts:
            archive.write(directory / part.path, part.path)
    return destination


def write_built_forms(document: dict[str, Any], directory: Path) -> PackagePart:
    """Write the built-forms part from *document* (``built_forms_document``)."""
    target = directory / PART_PATHS[PartKind.BUILT_FORMS]
    target.write_text(json.dumps(document, cls=DjangoJSONEncoder, indent=1))
    return PackagePart(
        kind=PartKind.BUILT_FORMS,
        path=PART_PATHS[PartKind.BUILT_FORMS],
        sha256=_sha256(target),
        rows=len(document["building_types"]),
    )


def export_geoparquet_parts(
    queries: dict[PartKind, tuple[str, str]], directory: Path
) -> list[PackagePart]:
    """Write one GeoParquet part per ``kind -> (PostGIS query, geometry column)``."""
    con = _duckdb_with_postgres()
    try:
        return [
            _write_geoparquet(
                con, kind=kind, query=query, geometry=geometry, directory=directory
            )
            for kind, (query, geometry) in queries.items()
        ]
    finally:
        con.close()


def export_workspace_package(
    workspace: Workspace, *, include_public_data: bool, destination: Path
) -> Path:
    """Write *workspace* as a workspace package at *destination* and return it.

    The package carries the base layer (``base_table`` — the source, not the
    built-form fill over it: the flag travels instead and the importer re-runs
    the fill), the Building Type library, the constraint layers and trip-length
    zones when they are the workspace's own (``*_source = package``), and — with
    *include_public_data* — its food outlets and road network, which are built
    first if no analysis has needed them yet.
    """
    if workspace.extent is None:
        msg = (
            f"Workspace {workspace.pk} has no extent (its base table "
            f"{workspace.base_table!r} has no geometry), so it cannot be exported."
        )
        raise PackageError(msg)
    kinds = _export_kinds(workspace, include_public_data=include_public_data)
    selectors = _input_selectors(workspace, kinds)
    if selectors:
        plan_fresh(select=selectors, skip_tests=True, auto_apply=True, no_prompts=True)
    with tempfile.TemporaryDirectory(prefix="brewgis-package-") as tmp:
        directory = Path(tmp)
        parts = export_geoparquet_parts(_part_queries(workspace, kinds), directory)
        parts.append(write_built_forms(built_forms_document(workspace), directory))
        return write_package(
            manifest_fields={
                "name": workspace.name,
                "local_srid": int(workspace.local_srid),
                "extent": extent_bounds(workspace.extent),
                "center_lng": workspace.center_lng,
                "center_lat": workspace.center_lat,
                "zoom": workspace.zoom,
                "fill_built_form": workspace.fill_built_form,
            },
            parts=parts,
            directory=directory,
            destination=destination,
        )


# ── Import ────────────────────────────────────────────────────────────


def _extract_verified(
    archive: zipfile.ZipFile, part: PackagePart, target: Path
) -> None:
    """Extract *part* into *target*, refusing it when its checksum is not the manifest's."""
    archive.extract(part.path, target)
    if _sha256(target / part.path) != part.sha256:
        msg = f"Part {part.kind.value} is corrupt: its checksum does not match the manifest."
        raise PackageError(msg)


def _unpack(archive_path: Path, manifest: PackageManifest, workspace: Workspace) -> str:
    """Extract *archive_path*'s parts for *workspace*; return the dir relative to MEDIA_ROOT.

    The directory is named after the manifest's checksum, so a re-attached
    package lands at a new path: the package bridges read their part by path,
    and a new path is a new model fingerprint, which is what makes SQLMesh
    rebuild them instead of keeping the previous package's rows.
    """
    manifest_digest = hashlib.sha256(
        json.dumps(manifest.to_dict(), sort_keys=True).encode()
    ).hexdigest()[:12]
    relative = f"{WORKSPACE_PACKAGES_DIR}/{workspace.pk}/{manifest_digest}"
    target = Path(settings.MEDIA_ROOT) / relative
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            archive.extract(MANIFEST_NAME, target)
            for part in manifest.parts:
                _extract_verified(archive, part, target)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return relative


def _remove_other_packages(workspace: Workspace) -> None:
    """Delete the workspace's unpacked packages other than the one it reads."""
    root = Path(settings.MEDIA_ROOT) / WORKSPACE_PACKAGES_DIR / str(workspace.pk)
    current = workspace.package_root()
    if not root.exists():
        return
    for child in root.iterdir():
        if current is None or child.resolve() != current.resolve():
            shutil.rmtree(child, ignore_errors=True)


def load_built_forms(workspace: Workspace, document: dict[str, Any]) -> int:
    """Replace *workspace*'s Building Type library with *document*'s; return the type count."""
    BuildingType.objects.filter(workspace=workspace).delete()
    PlaceType.objects.filter(workspace=workspace).delete()

    def build(model: type[Any], row: dict[str, Any]) -> Any:
        values = {
            model_field.name: model_field.to_python(row[model_field.name])
            for model_field in model._meta.concrete_fields  # noqa: SLF001
            if model_field.name not in _BUILT_FORM_SKIPPED_FIELDS
            and model_field.name in row
        }
        return model(workspace=workspace, **values)

    building_types = {
        building_type.name: building_type
        for building_type in BuildingType.objects.bulk_create(
            [build(BuildingType, row) for row in document.get("building_types", [])]
        )
    }
    place_types = {
        place_type.name: place_type
        for place_type in PlaceType.objects.bulk_create(
            [build(PlaceType, row) for row in document.get("place_types", [])]
        )
    }
    mixes = []
    for mix in document.get("mixes", []):
        try:
            place_type = place_types[mix["place_type"]]
            building_type = building_types[mix["building_type"]]
        except KeyError as error:
            msg = f"A place-type mix names a type the package does not define: {error}."
            raise PackageError(msg) from error
        mixes.append(
            PlaceTypeBuildingTypeMix(
                place_type=place_type,
                building_type=building_type,
                percentage=float(mix["percentage"]),
            )
        )
    PlaceTypeBuildingTypeMix.objects.bulk_create(mixes)
    return len(building_types)


def attach_package(
    workspace: Workspace,
    archive_path: Path,
    *,
    replace_library: bool,
    local_srid: int | None = None,
) -> PackageManifest:
    """Point *workspace*'s analysis inputs and base layer at the package at *archive_path*.

    Unpacks the parts, records them on the workspace (its CRS — the package's
    unless *local_srid* overrides it — extent, and which inputs are packaged)
    and, with *replace_library*, replaces its Building Types with the
    package's. The base canvas is built afterwards by ``build_package_base``,
    which runs a plan and so must run outside any request transaction.
    """
    manifest = open_package(archive_path)
    srid = manifest.local_srid if local_srid is None else local_srid
    try:
        validate_projected_srid(srid)
    except ValidationError as error:
        raise PackageError(error.messages[0]) from error
    package_dir = _unpack(archive_path, manifest, workspace)
    with zipfile.ZipFile(archive_path) as archive:
        built_forms = json.loads(archive.read(PART_PATHS[PartKind.BUILT_FORMS]))
    with transaction.atomic():
        workspace.package_dir = package_dir
        workspace.local_srid = srid
        workspace.extent = extent_polygon(*manifest.extent)
        workspace.constraint_source = (
            ConstraintSource.PACKAGE
            if manifest.has(PartKind.CONSTRAINT_LAYERS)
            else ConstraintSource.PUBLIC
        )
        workspace.trip_length_source = (
            TripLengthSource.PACKAGE
            if manifest.has(PartKind.TRIP_LENGTH_ZONES)
            else TripLengthSource.GRAVITY
        )
        workspace.public_data_source = (
            PublicDataSource.PACKAGE
            if manifest.has(PartKind.FOOD_POIS)
            else PublicDataSource.FETCH
        )
        workspace.save(
            update_fields=[
                "package_dir",
                "local_srid",
                "extent",
                "constraint_source",
                "trip_length_source",
                "public_data_source",
            ]
        )
        if replace_library:
            load_built_forms(workspace, built_forms)
    _remove_other_packages(workspace)
    return manifest


def import_workspace_package(
    archive_path: Path, *, name: str | None = None, local_srid: int | None = None
) -> Workspace:
    """Create a new workspace from the package at *archive_path*.

    The workspace gets the package's settings, its Building Type library and a
    base scenario; its base canvas is built by ``build_package_base``.
    """
    manifest = open_package(archive_path)
    package_root: Path | None = None
    try:
        with transaction.atomic():
            workspace = Workspace.objects.create(
                name=name or manifest.name,
                local_srid=manifest.local_srid if local_srid is None else local_srid,
                center_lng=manifest.center_lng,
                center_lat=manifest.center_lat,
                zoom=manifest.zoom,
                fill_built_form=manifest.fill_built_form,
            )
            package_root = (
                Path(settings.MEDIA_ROOT) / WORKSPACE_PACKAGES_DIR / str(workspace.pk)
            )
            # The workspace's own schema for its uploads and its exported
            # Building Types (``launch.BUILT_FORMS_TABLE``), named after its key
            # so it can never collide with another workspace's.
            workspace.db_schema = f"workspace_{workspace.pk}"
            workspace.base_table = f"{workspace.input_schema}.base_canvas"
            workspace.save(update_fields=["db_schema", "base_table"])
            attach_package(
                workspace, archive_path, replace_library=True, local_srid=local_srid
            )
            create_base_scenario(workspace)
    except BaseException:
        # The workspace row rolled back; its unpacked files must not outlive it.
        if package_root is not None:
            shutil.rmtree(package_root, ignore_errors=True)
        raise
    return workspace


def build_package_base(workspace: Workspace) -> None:
    """Build the packaged base canvas and adopt it as the workspace's base layer.

    The base canvas is a model of the workspace's own schema
    (``models/workspace_inputs/packaged_base_canvas.py``), built in the same plan as the
    scenario canvases over it. A workspace exported with the built-form fill on
    gets it back here: the fill reads the built base, so it is planned once the
    base exists.
    """
    base_table = f"{workspace.input_schema}.base_canvas"
    fill = workspace.fill_built_form
    adopt_base_table(
        workspace,
        base_table=base_table,
        fill_built_form=False,
        extent=workspace.extent,
        base_selectors=[f"+brewgis.{base_table}"],
    )
    if fill:
        adopt_base_table(
            workspace,
            base_table=base_table,
            fill_built_form=True,
            extent=workspace.extent,
        )

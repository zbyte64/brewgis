"""dlt pipeline assets via ``@dlt_assets`` decorator.

Wraps the existing 3 dlt pipelines (census ACS, LEHD LODES WAC, Overpass POI)
plus the raster pipeline as Dagster software-defined assets. Each asset group
corresponds to one dlt source and produces a staging table in PostGIS.

Contract metadata is injected via ``DagsterDltTranslator`` subclass rather than
the ``@dlt_assets`` decorator's ``metadata`` parameter (which is not supported
in the current Dagster version).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import dlt
from dagster import Config
from dagster_embedded_elt.dlt import DagsterDltResource
from dagster_embedded_elt.dlt import DagsterDltTranslator
from dagster_embedded_elt.dlt import dlt_assets

if TYPE_CHECKING:
    from collections.abc import Mapping

from brewgis.workspace.dagster.check_provenance import METADATA_CONTRACT_INLINE_COLUMNS
from brewgis.workspace.dagster.check_provenance import METADATA_CONTRACT_PATH
from brewgis.workspace.dagster.check_provenance import METADATA_CONTRACT_SOURCE
from brewgis.workspace.dlt_pipelines.census import census_source
from brewgis.workspace.dlt_pipelines.lehd import lehd_source
from brewgis.workspace.dlt_pipelines.poi import poi_source
from brewgis.workspace.dlt_pipelines.raster import raster_band_source
from brewgis.workspace.dlt_pipelines.raster import raster_metadata_source

_STAGING_SCHEMA = "public"


class RasterIngestConfig(Config):
    """Configuration for raster ingestion assets.

    Requires a ``file_path`` pointing to the GeoTIFF/COG file to ingest.
    """

    file_path: str


# ---------------------------------------------------------------------------
# Contract-aware dlt translator
# ---------------------------------------------------------------------------


class _ContractDltTranslator(DagsterDltTranslator):
    """DagsterDltTranslator that injects contract metadata on dlt assets.

    Each known pipeline name maps to its contract source and (optionally)
    inline columns.
    """

    def __init__(self) -> None:
        self._contracts: dict[str, dict[str, Any]] = {
            "census_acs": {
                METADATA_CONTRACT_SOURCE: "soda",
                METADATA_CONTRACT_PATH: "census_acs",
            },
            "lehd_lodes": {
                METADATA_CONTRACT_SOURCE: "soda",
                METADATA_CONTRACT_PATH: "lehd",
            },
            "overpass_poi": {
                METADATA_CONTRACT_SOURCE: "soda",
                METADATA_CONTRACT_PATH: "poi",
            },
            "raster_metadata": {
                METADATA_CONTRACT_SOURCE: "inline",
                METADATA_CONTRACT_INLINE_COLUMNS: [
                    "width",
                    "height",
                    "crs",
                    "bounds",
                    "file_path",
                ],
            },
            "raster_bands": {
                METADATA_CONTRACT_SOURCE: "inline",
                METADATA_CONTRACT_INLINE_COLUMNS: [
                    "band_index",
                    "min",
                    "max",
                    "mean",
                    "stddev",
                ],
            },
        }

    def get_metadata(
        self, resource: dlt.extract.resource.DltResource
    ) -> Mapping[str, Any]:
        """Return contract metadata for *resource* based on its pipeline name."""
        pipeline_name = resource.source_name or ""
        return self._contracts.get(pipeline_name, {})


_CONTRACT_TRANSLATOR = _ContractDltTranslator()


# ---------------------------------------------------------------------------
# Census ACS
# ---------------------------------------------------------------------------


@dlt_assets(
    dlt_source=census_source(),
    dlt_pipeline=dlt.pipeline(
        pipeline_name="census_acs",
        destination="postgres",
        dataset_name=_STAGING_SCHEMA,
    ),
    group_name="raw_data",
    dagster_dlt_translator=_CONTRACT_TRANSLATOR,
)
def census_acs_assets(context, dlt: DagsterDltResource) -> Any:
    """Materialize raw Census ACS 5-year data into PostGIS staging."""
    yield from dlt.run(context=context)


# ---------------------------------------------------------------------------
# LEHD LODES WAC
# ---------------------------------------------------------------------------


@dlt_assets(
    dlt_source=lehd_source(),
    dlt_pipeline=dlt.pipeline(
        pipeline_name="lehd_lodes",
        destination="postgres",
        dataset_name=_STAGING_SCHEMA,
    ),
    group_name="raw_data",
    dagster_dlt_translator=_CONTRACT_TRANSLATOR,
)
def lehd_lodes_assets(context, dlt: DagsterDltResource) -> Any:
    """Materialize raw LEHD LODES WAC data into PostGIS staging."""
    yield from dlt.run(context=context)


# ---------------------------------------------------------------------------
# Overpass POI
# ---------------------------------------------------------------------------


@dlt_assets(
    dlt_source=poi_source(),
    dlt_pipeline=dlt.pipeline(
        pipeline_name="overpass_poi",
        destination="postgres",
        dataset_name=_STAGING_SCHEMA,
    ),
    group_name="raw_data",
    dagster_dlt_translator=_CONTRACT_TRANSLATOR,
)
def overpass_poi_assets(context, dlt: DagsterDltResource) -> Any:
    """Materialize raw Overpass POI data into PostGIS staging."""
    yield from dlt.run(context=context)


# ---------------------------------------------------------------------------
# Raster metadata
# ---------------------------------------------------------------------------


@dlt_assets(
    dlt_source=raster_metadata_source(file_path=""),
    dlt_pipeline=dlt.pipeline(
        pipeline_name="raster_metadata",
        destination="postgres",
        dataset_name=_STAGING_SCHEMA,
    ),
    group_name="raster",
    dagster_dlt_translator=_CONTRACT_TRANSLATOR,
)
def raster_metadata_assets(context, dlt: DagsterDltResource) -> Any:
    """Extract GeoTIFF/COG metadata (width, height, CRS, bounds) to staging."""
    yield from dlt.run(context=context)


# ---------------------------------------------------------------------------
# Raster band statistics
# ---------------------------------------------------------------------------


@dlt_assets(
    dlt_source=raster_band_source(file_path=""),
    dlt_pipeline=dlt.pipeline(
        pipeline_name="raster_bands",
        destination="postgres",
        dataset_name=_STAGING_SCHEMA,
    ),
    group_name="raster",
    dagster_dlt_translator=_CONTRACT_TRANSLATOR,
)
def raster_band_assets(context, dlt: DagsterDltResource) -> Any:
    """Extract per-band statistics (min, max, mean, stddev) from GeoTIFF."""
    yield from dlt.run(context=context)

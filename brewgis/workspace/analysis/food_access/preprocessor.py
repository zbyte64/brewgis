# ruff: noqa: S608 — schema/table names cannot be SQL bind parameters
"""Modified Retail Food Environment Index (mRFEI) preprocessor.

Computes the Modified Retail Food Environment Index per parcel using
OpenStreetMap Points of Interest:

    mRFEI = healthy / (healthy + unhealthy) * 100

Healthy sources: supermarkets, grocery stores, farmers markets.
Unhealthy sources: convenience stores, fast food.

Workflow:
    1. Reads parcel bounding box from the end-state table.
    2. Fetches food-related POIs from OSM Overpass API via ``fetch_pois``.
    3. Classifies POIs as healthy or unhealthy by OSM tag.
    4. Counts healthy/unhealthy POIs within 1 km of each parcel.
    5. Computes mRFEI and writes to ``food_access_inputs_{scenario_id}``.

Convention:
    Output table: ``{target_schema}.food_access_inputs_{scenario_id}``
    Columns: ``parcel_id``, ``healthy_count``, ``unhealthy_count``, ``mrfei``, ``geom``
"""

from __future__ import annotations

import logging
import re
from typing import Any
import geopandas as gpd
from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text
from brewgis.workspace.models import POICache
from brewgis.workspace.services.poi_fetcher import fetch_pois

logger = logging.getLogger(__name__)

# Tags that classify a POI as a healthy food source
_HEALTHY_TAGS: set[str] = {
    "shop=supermarket",
    "shop=grocery",
    "shop=farmers_market",
    "shop=grocer",
}

# Tags that classify a POI as an unhealthy food source
_UNHEALTHY_TAGS: set[str] = {
    "shop=convenience",
    "shop=convenience_store",
    "amenity=fast_food",
}

# Categories requested from the POI fetcher — covers all food-related POIs
_REQUESTED_CATEGORIES: list[str] = ["shopping", "restaurants"]


class FoodAccessPreprocessor:
    """Compute Modified Retail Food Environment Index (mRFEI) per parcel.

    Uses OSM POI data within 1 km of each parcel centroid to calculate
    the ratio of healthy to total food retailers.
    """

    def __init__(self) -> None:
        self._engine: Any = None

    @property
    def engine(self) -> Any:
        """Lazy-initialized SQLAlchemy engine from centralized _db module."""
        if self._engine is None:
            self._engine = get_engine()
        return self._engine

    def _get_bbox(
        self, schema: str, end_state_table: str
    ) -> tuple[float, float, float, float]:
        """Get the bounding box of all parcel geometries.

        Returns:
            Tuple of (min_lng, min_lat, max_lng, max_lat).
        """
        sql = text(
            f"SELECT ST_Extent(geom) FROM {schema}.{end_state_table} "
            f"WHERE geom IS NOT NULL"
        )
        with self.engine.connect() as conn:
            row = conn.execute(sql).fetchone()
        extent = row[0] if row else None
        if extent is None:
            raise RuntimeError(
                "No geometries found in end_state_table — cannot compute bbox"
            )

        # ST_Extent returns "BOX(minx miny, maxx maxy)" in the text format
        match = re.search(r"BOX\(([\d.-]+) ([\d.-]+), ([\d.-]+) ([\d.-]+)\)", extent)
        if not match:
            raise RuntimeError(f"Could not parse ST_Extent result: {extent}")

        return (
            float(match.group(1)),
            float(match.group(2)),
            float(match.group(3)),
            float(match.group(4)),
        )

    def compute_mrfei(
        self,
        schema: str,
        end_state_table: str,
        scenario_id: str,
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        """Compute mRFEI for all parcels in the end-state table.

        Args:
            schema: Target PostGIS schema.
            end_state_table: Core end-state table (may contain
                ``{scenario_id}`` placeholder).
            scenario_id: Scenario identifier for table naming.

        Returns:
            Dict with keys:
                success (bool)
                input_table (str, on success): Fully qualified output table name.
                error (str, on failure): Error message.
        """
        resolved_end_state = end_state_table.replace("{scenario_id}", scenario_id)
        output_table = f"{schema}.food_access_inputs_{scenario_id}"
        temp_poi_table = f"{schema}.food_pois_{scenario_id}"

        logger.info("Computing mRFEI: %s -> %s", resolved_end_state, output_table)

        # Step 1: Get parcel bounding box
        min_lng, min_lat, max_lng, max_lat = self._get_bbox(
            schema=schema, end_state_table=resolved_end_state
        )
        logger.debug(
            "Parcel bbox: (%.6f, %.6f) -> (%.6f, %.6f)",
            min_lng,
            min_lat,
            max_lng,
            max_lat,
        )

        # Step 2: Fetch food-related POIs via dlt pipeline + staging
        from brewgis.workspace.dlt_pipelines.poi import run_poi_pipeline
        dlt_result = run_poi_pipeline(
            min_lng, min_lat, max_lng, max_lat,
            categories=_REQUESTED_CATEGORIES,
            schema=schema,
        )
        if not dlt_result.get("success"):
            logger.warning("POI dlt pipeline failed: %s", dlt_result.get("error"))
        else:
            logger.info("dlt pipeline loaded %d raw POIs", dlt_result.get("row_count", 0))

        pois = fetch_pois(
            min_lng=min_lng,
            min_lat=min_lat,
            max_lng=max_lng,
            max_lat=max_lat,
            categories=_REQUESTED_CATEGORIES,
        )
        logger.info("Fetched %d POIs from Overpass", len(pois))
        # Cache the successful POI fetch for offline fallback
        if workspace_id is not None:
            try:
                POICache.objects.update_or_create(
                    workspace_id=workspace_id,
                    name="food_poi",
                    defaults={
                        "geojson_data": pois.__geo_interface__,
                        "source": "osm",
                    },
                )
            except Exception as cache_err:
                logger.warning("Failed to cache POI data: %s", cache_err)

        # Step 3: Classify POIs
        pois["is_healthy"] = pois["subcategory"].isin(_HEALTHY_TAGS)
        pois["is_unhealthy"] = pois["subcategory"].isin(_UNHEALTHY_TAGS)
        food_pois = pois[pois["is_healthy"] | pois["is_unhealthy"]].copy()

        logger.info(
            "Classified %d food-related POIs (%d healthy, %d unhealthy)",
            len(food_pois),
            int(food_pois["is_healthy"].sum()) if not food_pois.empty else 0,
            int(food_pois["is_unhealthy"].sum()) if not food_pois.empty else 0,
        )

        # Step 4: Write food POIs to temp table for spatial join
        self._write_temp_poi_table(
            schema=schema,
            table_name=temp_poi_table,
            food_pois=food_pois,
        )

        # Step 5: Compute and write mRFEI
        self._compute_and_write(
            schema=schema,
            end_state_table=resolved_end_state,
            output_table=output_table,
            temp_poi_table=temp_poi_table,
        )
        # Clean up temp table
        with self.engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {temp_poi_table} CASCADE"))

        logger.info("mRFEI written to %s", output_table)
        return {"success": True, "input_table": output_table}

    def _write_temp_poi_table(
        self,
        schema: str,
        table_name: str,
        food_pois: gpd.GeoDataFrame,
    ) -> None:
        """Create and populate a temporary table with classified food POIs."""
        with self.engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
            conn.execute(
                text(
                    f"CREATE TABLE {table_name} ("
                    f"  osm_id BIGINT NOT NULL,"
                    f"  is_healthy BOOLEAN NOT NULL,"
                    f"  is_unhealthy BOOLEAN NOT NULL,"
                    f"  geom GEOMETRY(Point, 4326)"
                    f")"
                )
            )

        if food_pois.empty:
            logger.info("No food POIs to insert (empty table will be left empty)")
            return

        insert_sql = text(
            f"INSERT INTO {table_name} (osm_id, is_healthy, is_unhealthy, geom) "
            f"VALUES (:osm_id, :is_healthy, :is_unhealthy, "
            f"ST_GeomFromText(:geom_wkt, 4326))"
        )
        with self.engine.begin() as conn:
            batch: list[dict[str, Any]] = []
            for _, row in food_pois.iterrows():
                batch.append(
                    {
                        "osm_id": int(row["osm_id"]),
                        "is_healthy": bool(row["is_healthy"]),
                        "is_unhealthy": bool(row["is_unhealthy"]),
                        "geom_wkt": row.geometry.wkt,
                    }
                )
            conn.execute(insert_sql, batch)

        logger.info("Inserted %d food POIs into %s", len(food_pois), table_name)

    def _compute_and_write(
        self,
        schema: str,
        end_state_table: str,
        output_table: str,
        temp_poi_table: str,
    ) -> None:
        """Compute mRFEI per parcel via spatial join and write the output table."""
        with self.engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            conn.execute(text(f"DROP TABLE IF EXISTS {output_table} CASCADE"))
            conn.execute(
                text(
                    f"CREATE TABLE {output_table} AS "
                    f"SELECT "
                    f"  es.parcel_id,"
                    f"  COALESCE(SUM(CASE WHEN fp.is_healthy THEN 1 ELSE 0 END), 0) "
                    f"    AS healthy_count,"
                    f"  COALESCE(SUM(CASE WHEN fp.is_unhealthy THEN 1 ELSE 0 END), 0) "
                    f"    AS unhealthy_count,"
                    f"  CASE"
                    f"    WHEN COUNT(fp.osm_id) = 0 THEN NULL"
                    f"    ELSE"
                    f"      SUM(CASE WHEN fp.is_healthy THEN 1 ELSE 0 END)::DOUBLE PRECISION"
                    f"      / NULLIF("
                    f"          SUM(CASE WHEN fp.is_healthy THEN 1 ELSE 0 END)"
                    f"          + SUM(CASE WHEN fp.is_unhealthy THEN 1 ELSE 0 END),"
                    f"          0"
                    f"      )"
                    f"      * 100.0"
                    f"  END AS mrfei,"
                    f"  es.geom"
                    f" FROM {schema}.{end_state_table} AS es"
                    f" LEFT JOIN {temp_poi_table} AS fp"
                    f"   ON ST_DWithin(es.geom::geography, fp.geom::geography, 1000)"
                    f" GROUP BY es.parcel_id, es.geom"
                )
            )

        logger.info("Computed and wrote mRFEI to %s", output_table)

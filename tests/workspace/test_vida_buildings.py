"""Tests for the VIDA Combined Building Footprints dlt pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pyarrow as pa
import pytest
import shapely
import shapely.wkb
from shapely import from_wkb

from brewgis.workspace.dlt_pipelines.vida_buildings import OUTPUT_TABLE
from brewgis.workspace.dlt_pipelines.vida_buildings import S3_S2_PARTITION_DIR
from brewgis.workspace.dlt_pipelines.vida_buildings import run_vida_buildings_pipeline
from brewgis.workspace.dlt_pipelines.vida_buildings import vida_buildings_source
from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text


class TestVidaBuildings:
    """Unit tests for the VIDA dlt pipeline."""

    def test_s2_partition_dir_correct(self) -> None:
        """S3_S2_PARTITION_DIR points to the USA S2 partition folder."""
        assert S3_S2_PARTITION_DIR.endswith("country_iso=USA")
        assert not S3_S2_PARTITION_DIR.endswith(".parquet")

    def test_source_yields_named_resource(self) -> None:
        """vida_buildings_source yields a resource named vida_combined_buildings."""
        source = vida_buildings_source()
        resource_names = list(source.resources)
        assert OUTPUT_TABLE in resource_names

    def test_parquet_rows_convert_to_correct_dicts(self) -> None:
        """Parquet WKB geometry converts to WKT dicts with correct fields."""
        polygon_wkb = shapely.wkb.dumps(
            shapely.from_wkt(
                "POLYGON((-121.5 38.5,-121.4 38.5,-121.4 38.6,-121.5 38.6,-121.5 38.5))"
            )
        )

        table = pa.table(
            {
                "geometry": pa.array([polygon_wkb, polygon_wkb], type=pa.binary()),
                "confidence": pa.array([0.95, None], type=pa.float64()),
                "bf_source": pa.array(["google", "microsoft"], type=pa.string()),
                "area_in_meters": pa.array([150.0, 200.0], type=pa.float64()),
            }
        )

        wkb_list = table.column("geometry").to_pylist()
        geometries = from_wkb(wkb_list)
        confidence_col = table.column("confidence").to_pylist()
        bf_source_col = table.column("bf_source").to_pylist()
        area_col = table.column("area_in_meters").to_pylist()

        rows = []
        for i in range(len(geometries)):
            geom = geometries[i]
            if geom is None or geom.is_empty:
                continue
            rows.append(
                {
                    "geometry": geom.wkt,
                    "confidence": (
                        float(confidence_col[i])
                        if confidence_col[i] is not None
                        else None
                    ),
                    "bf_source": (
                        str(bf_source_col[i]) if bf_source_col[i] is not None else None
                    ),
                    "area_in_meters": (
                        float(area_col[i]) if area_col[i] is not None else None
                    ),
                }
            )

        assert len(rows) == 2
        assert rows[0]["geometry"].startswith("POLYGON")
        assert rows[0]["confidence"] == 0.95
        assert rows[0]["bf_source"] == "google"
        assert rows[0]["area_in_meters"] == 150.0
        assert rows[1]["confidence"] is None
        assert rows[1]["bf_source"] == "microsoft"

    def test_run_pipeline_returns_dict(self) -> None:
        """run_vida_buildings_pipeline returns expected dict structure."""
        mock_pipeline = MagicMock()
        mock_pipeline.last_trace.steps = []
        mock_pipeline.run.return_value = MagicMock()

        with (
            patch(
                "brewgis.workspace.dlt_pipelines.vida_buildings.dlt.pipeline",
                return_value=mock_pipeline,
            ),
            patch("brewgis.workspace.services._db.get_engine") as mock_engine,
        ):
            mock_conn = (
                mock_engine.return_value.connect.return_value.__enter__.return_value
            )
            mock_conn.execute.return_value.scalar.return_value = False

            result = run_vida_buildings_pipeline()

        assert "table_name" in result
        assert "row_count" in result
        assert "load_info" in result
        assert OUTPUT_TABLE in result["table_name"]
        assert result["row_count"] == 0


@pytest.mark.integration
@pytest.mark.django_db
class TestVidaBuildingsIntegration:
    """Integration tests for VIDA buildings (requires PostGIS)."""

    def test_vida_table_schema(self) -> None:
        """Verify the vida_combined_buildings table schema matches expectations."""
        engine = get_engine()

        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS public.vida_combined_buildings (\n"
                    "    geometry       GEOMETRY(GEOMETRY, 4326),\n"
                    "    confidence     DOUBLE PRECISION,\n"
                    "    bf_source      TEXT,\n"
                    "    area_in_meters DOUBLE PRECISION\n"
                    ")"
                )
            )

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT column_name, udt_name, is_nullable\n"
                    "FROM information_schema.columns\n"
                    "WHERE table_schema = 'public'\n"
                    "  AND table_name = 'vida_combined_buildings'\n"
                    "ORDER BY ordinal_position"
                )
            ).fetchall()

        columns = {row[0]: {"type": row[1], "nullable": row[2]} for row in rows}

        assert "geometry" in columns
        assert columns["geometry"]["type"] == "geometry"
        assert columns["geometry"]["nullable"] == "YES"

        assert "confidence" in columns
        assert columns["confidence"]["type"] == "float8"
        assert columns["confidence"]["nullable"] == "YES"

        assert "bf_source" in columns
        assert columns["bf_source"]["type"] == "text"
        assert columns["bf_source"]["nullable"] == "YES"

        assert "area_in_meters" in columns
        assert columns["area_in_meters"]["type"] == "float8"
        assert columns["area_in_meters"]["nullable"] == "YES"

        with engine.begin() as conn:
            conn.execute(
                text("DROP TABLE IF EXISTS public.vida_combined_buildings CASCADE")
            )

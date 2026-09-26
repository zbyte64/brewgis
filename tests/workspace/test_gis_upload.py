# ruff: noqa: ANN201, ARG002
"""Tests for the GIS file upload.

Covering what the form accepts (extensions, compound extensions, size limits)
and what the ingest writes: a file that is itself a base canvas has to land at
the types the base-canvas contract needs, or the table it produces cannot be
adopted as a workspace's base canvas at all.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import geopandas as gpd
import pytest
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db import connection
from shapely.geometry import Polygon

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.views.read_gis_file import ImportGISFileForm
from brewgis.workspace.views.read_gis_file import read_gis_file_into_table


class TestImportGISFileFormValidation:
    """Tests for ImportGISFileForm clean_file method."""

    def _make_file(
        self, name: str, content: bytes = b"{}", size: int | None = None
    ) -> InMemoryUploadedFile:
        """Create an in-memory file for testing."""
        if size is not None:
            content = b"x" * size
        return InMemoryUploadedFile(
            file=io.BytesIO(content),
            field_name="file",
            name=name,
            content_type="application/octet-stream",
            size=len(content),
            charset=None,
        )

    def test_valid_geojson_extension(self):
        """GeoJSON files pass validation."""
        form = ImportGISFileForm(
            data={"workspace": "", "table_name": "test"},
            files={"file": self._make_file("test.geojson")},
        )
        assert form.is_valid() is False
        assert "Unsupported file type" not in str(form.errors.get("file", ""))

    def test_valid_gpkg_extension(self):
        """GeoPackage files pass validation."""
        form = ImportGISFileForm(
            data={"workspace": "", "table_name": "test"},
            files={"file": self._make_file("data.gpkg")},
        )
        assert form.is_valid() is False
        assert "Unsupported file type" not in str(form.errors.get("file", ""))

    def test_valid_shp_zip_compound_extension(self):
        """.shp.zip compound extension passes validation."""
        form = ImportGISFileForm(
            data={"workspace": "", "table_name": "test"},
            files={"file": self._make_file("parcels.shp.zip")},
        )
        assert form.is_valid() is False
        assert "Unsupported file type" not in str(form.errors.get("file", ""))

    def test_valid_csv_extension(self):
        """CSV files pass validation."""
        form = ImportGISFileForm(
            data={"workspace": "", "table_name": "test"},
            files={"file": self._make_file("data.csv")},
        )
        assert form.is_valid() is False
        assert "Unsupported file type" not in str(form.errors.get("file", ""))

    def test_invalid_txt_extension_raises_error(self):
        """Unsupported .txt extension raises ValidationError."""
        form = ImportGISFileForm(
            data={"workspace": "", "table_name": "test"},
            files={"file": self._make_file("data.txt")},
        )
        assert form.is_valid() is False
        file_errors = str(form.errors.get("file", ""))
        assert "Unsupported file type" in file_errors
        assert ".txt" in file_errors
        assert ".geojson" in file_errors

    def test_invalid_pdf_extension_raises_error(self):
        """Unsupported .pdf extension raises ValidationError."""
        form = ImportGISFileForm(
            data={"workspace": "", "table_name": "test"},
            files={"file": self._make_file("map.pdf")},
        )
        assert form.is_valid() is False
        file_errors = str(form.errors.get("file", ""))
        assert "Unsupported file type" in file_errors
        assert ".pdf" in file_errors

    def test_no_extension_raises_error(self):
        """File with no extension raises ValidationError."""
        form = ImportGISFileForm(
            data={"workspace": "", "table_name": "test"},
            files={"file": self._make_file("README")},
        )
        assert form.is_valid() is False
        file_errors = str(form.errors.get("file", ""))
        assert "Unsupported file type" in file_errors

    @patch(
        "brewgis.workspace.views.read_gis_file.settings.MAX_UPLOAD_SIZE",
        new=100,
    )
    def test_file_too_large_raises_error(self):
        """File exceeding MAX_UPLOAD_SIZE raises ValidationError."""
        form = ImportGISFileForm(
            data={"workspace": "", "table_name": "test"},
            files={"file": self._make_file("data.geojson", size=200)},
        )
        assert form.is_valid() is False
        file_errors = str(form.errors.get("file", ""))
        assert "File too large" in file_errors

    @patch(
        "brewgis.workspace.views.read_gis_file.settings.MAX_UPLOAD_SIZE",
        new=1024 * 1024,
    )
    def test_file_within_size_limit_passes(self):
        """File within MAX_UPLOAD_SIZE passes extension validation."""
        form = ImportGISFileForm(
            data={"workspace": "", "table_name": "test"},
            files={"file": self._make_file("data.geojson", size=500)},
        )
        assert form.is_valid() is False
        assert "File too large" not in str(form.errors.get("file", ""))

    def test_valid_kml_extension(self):
        """KML files pass validation."""
        form = ImportGISFileForm(
            data={"workspace": "", "table_name": "test"},
            files={"file": self._make_file("places.kml")},
        )
        assert form.is_valid() is False
        assert "Unsupported file type" not in str(form.errors.get("file", ""))

    def test_valid_parquet_extension(self):
        """Parquet files pass validation."""
        form = ImportGISFileForm(
            data={"workspace": "", "table_name": "test"},
            files={"file": self._make_file("data.parquet")},
        )
        assert form.is_valid() is False
        assert "Unsupported file type" not in str(form.errors.get("file", ""))


@pytest.mark.integration
class TestBaseCanvasIngest:
    """An uploaded base canvas lands at the types the base-canvas contract needs.

    The picker checks column *types* against the database, not the file (see
    ``sqlmesh_tables._column_type_requirement``), so a file that carries the
    right columns has to be written at the right types or the table it produces
    is not adoptable at all. GeoJSON has no column types: a column that is empty
    in every row reads back as an object column, which ``to_postgis`` would
    write as ``text`` — measured on the SACOG parcels, where that is a normal
    state for the sparser columns.
    """

    @pytest.fixture
    def table_name(self) -> str:
        """A table name no other worker of this run can collide with."""
        return f"test_imported_base_canvas_{uuid4().hex[:8]}"

    def _write_file(self, path) -> str:
        row: dict[str, object] = dict.fromkeys(BaseCanvasSchema.COLUMN_NAMES)
        row["parcel_id"] = 1
        row["built_form_key"] = "sfr"
        row["geometry"] = Polygon(
            [(0, 0), (0, 0.001), (0.001, 0.001), (0.001, 0), (0, 0)]
        )
        frame = gpd.GeoDataFrame([row], crs="EPSG:4326")
        frame.to_file(path, driver="GeoJSON")
        assert frame["du"].dtype == object or frame["du"].dtype == float, frame.dtypes
        return str(path)

    def _drop(self, table: str) -> None:
        """Drop *table* on the engine that created it.

        The ingest writes through SQLAlchemy, not Django's connection — so
        neither the table nor a ``DROP`` issued on Django's connection (which
        the test's transaction rolls back) is part of this test's transaction.
        """
        with get_engine().begin() as connection_:
            connection_.execute(text(f'DROP TABLE IF EXISTS public."{table}"'))

    def _column_types(self, table: str) -> dict[str, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s",
                [table],
            )
            return dict(cursor.fetchall())

    def test_numeric_columns_are_written_as_numbers(self, db, tmp_path, table_name):
        path = self._write_file(tmp_path / "base_canvas.geojson")
        try:
            with Path(path).open("rb") as handle:
                read_gis_file_into_table(handle, "public", table_name)

            types = self._column_types(table_name)
            assert types["du"] == "double precision"
            assert types["built_form_key"] == "text"
            for name in BaseCanvasSchema.PAINTABLE_COLUMNS:
                if name in BaseCanvasSchema.TEXT_COLUMNS:
                    continue
                assert types[name] == "double precision", (name, types[name])
        finally:
            self._drop(table_name)

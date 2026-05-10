# ruff: noqa: ANN201
"""Tests for GIS file upload validation — ImportGISFileForm clean_file.

Tests cover file extension checking, compound extensions, and size limits.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from django.core.files.uploadedfile import InMemoryUploadedFile

from brewgis.workspace.views.read_gis_file import ImportGISFileForm


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

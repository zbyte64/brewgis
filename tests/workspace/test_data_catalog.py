"""Tests for the Data Catalog models."""

from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.test import TestCase

from brewgis.workspace.models import DataSource
from brewgis.workspace.models import DataSourceCategory


@pytest.mark.models
class TestDataSourceCategoryModel(TestCase):
    """Tests for DataSourceCategory model."""

    def setUp(self) -> None:
        self.category = DataSourceCategory.objects.create(
            name="Test Boundaries",
            slug="test-boundaries",
            description="Administrative boundaries",
            icon="bi-bounding-box-circles",
            sort_order=100,
        )

    def test_category_str(self) -> None:
        """__str__ returns the category name."""
        assert str(self.category) == "Test Boundaries"

    def test_category_slug_unique(self) -> None:
        """Duplicate slugs are rejected."""
        with pytest.raises(IntegrityError):
            DataSourceCategory.objects.create(
                name="Other",
                slug="test-boundaries",  # same slug
            )

    def test_category_ordering(self) -> None:
        """Categories are ordered by sort_order then name."""
        DataSourceCategory.objects.create(
            name="Test People",
            slug="test-people",
            sort_order=101,
        )
        DataSourceCategory.objects.create(
            name="Test Land Use",
            slug="test-land-use",
            sort_order=102,
        )
        cats = list(DataSourceCategory.objects.filter(slug__startswith="test-"))
        assert len(cats) == 3
        assert cats[0].slug == "test-boundaries"
        assert cats[1].slug == "test-people"
        assert cats[2].slug == "test-land-use"

    def test_verbose_name_plural(self) -> None:
        """Verbose plural is correctly set."""
        assert DataSourceCategory._meta.verbose_name_plural == "Data Source Categories"


@pytest.mark.models
class TestDataSourceModel(TestCase):
    """Tests for DataSource model."""

    def setUp(self) -> None:
        self.category = DataSourceCategory.objects.create(
            name="Test Boundaries",
            slug="test-boundaries",
            sort_order=1,
        )
        self.source = DataSource.objects.create(
            category=self.category,
            name="Test TIGER/Line",
            slug="test-tiger-line",
            description="Census boundaries",
            provider="U.S. Census Bureau",
            provider_url="https://www.census.gov",
            data_format="shapefile",
            update_frequency="annual",
            acquisition_priority="p0",
            icon="bi-bounding-box-circles",
            sort_order=1,
        )

    def test_source_str(self) -> None:
        """__str__ includes name and category."""
        assert "Test TIGER/Line" in str(self.source)
        assert "Test Boundaries" in str(self.source)

    def test_source_slug_unique(self) -> None:
        """Duplicate source slugs are rejected."""
        with pytest.raises(IntegrityError):
            DataSource.objects.create(
                category=self.category,
                name="Other",
                slug="test-tiger-line",  # same slug
                provider="Other",
            )

    def test_source_category_relation(self) -> None:
        """DataSource relates to DataSourceCategory via FK."""
        assert self.source.category == self.category
        assert self.source in self.category.sources.all()

    def test_default_is_not_importable(self) -> None:
        """is_importable defaults to False."""
        assert self.source.is_importable is False

    def test_blank_fields_default(self) -> None:
        """Optional fields default to empty string."""
        assert self.source.description == "Census boundaries"
        assert self.source.icon is not None

    def test_cascade_delete(self) -> None:
        """Deleting a category cascades to its sources."""
        pk = self.source.pk
        self.category.delete()
        with pytest.raises(DataSource.DoesNotExist):
            DataSource.objects.get(pk=pk)

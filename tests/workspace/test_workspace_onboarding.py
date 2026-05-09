"""Tests for workspace onboarding (create, detail, home, county model)."""

from __future__ import annotations

import pytest
from django.db.utils import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils.text import slugify

from brewgis.workspace.models import County
from brewgis.workspace.models import Workspace
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory


@pytest.mark.models
class TestCountyModel(TestCase):
    """Tests for the County model and seed data."""

    def test_counties_seeded(self) -> None:
        """Counties should be seeded from migration."""
        count = County.objects.count()
        assert count > 3000

    def test_state_filter(self) -> None:
        """Should filter counties by state FIPS."""
        ca_counties = County.objects.filter(state_fips="06")
        assert ca_counties.count() == 58

    def test_county_detail(self) -> None:
        """Should find specific county by state + county FIPS."""
        fresno = County.objects.filter(state_fips="06", county_fips="019").first()
        assert fresno is not None
        assert fresno.name == "Fresno County"

    def test_str(self) -> None:
        """__str__ should return county name and FIPS."""
        c = County.objects.filter(state_fips="06", county_fips="019").first()
        assert c is not None
        assert "Fresno County" in str(c)
        assert "06019" in str(c)

    def test_unique_together(self) -> None:
        """Duplicate state_fips + county_fips should raise."""
        County.objects.create(state_fips="99", county_fips="999", name="Test")
        with pytest.raises(IntegrityError):
            County.objects.create(state_fips="99", county_fips="999", name="Duplicate")


@pytest.mark.views
class TestWorkspaceCreateView(TestCase):
    """Tests for the workspace creation view."""

    def setUp(self) -> None:
        self.user = UserFactory()

    def test_get_requires_auth(self) -> None:
        """Unauthenticated GET should redirect."""
        url = reverse("workspace:workspace_create")
        response = self.client.get(url)
        assert response.status_code == 302

    def test_get_authenticated(self) -> None:
        """Authenticated GET should render the form."""
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_create")
        response = self.client.get(url)
        assert response.status_code == 200
        assert b"Create Workspace" in response.content
        assert b"State" in response.content

    def test_state_dropdown_has_all_states(self) -> None:
        """State dropdown should include all 50 states + DC."""
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_create")
        response = self.client.get(url)
        assert response.status_code == 200
        assert b"California" in response.content
        assert b"Alabama" in response.content
        assert b"District of Columbia" in response.content

    def test_county_options_htmx(self) -> None:
        """HTMX request for county_options should return county checkboxes."""
        self.client.force_login(self.user)
        url = reverse("workspace:county_options")
        response = self.client.get(url, {"state": "06"})
        assert response.status_code == 200
        assert b"Fresno County" in response.content
        assert b"Los Angeles County" in response.content
        assert b'name="county_fips"' in response.content

    def test_county_options_empty_state(self) -> None:
        """HTMX request with invalid state should return empty."""
        self.client.force_login(self.user)
        url = reverse("workspace:county_options")
        response = self.client.get(url, {"state": "99"})
        assert response.status_code == 200
        assert b"No counties found" in response.content

    def test_post_creates_workspace_with_counties(self) -> None:
        """POST should create workspace with county_fips_list."""
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_create")
        response = self.client.post(
            url,
            {
                "name": "Fresno Analysis",
                "description": "Testing workspace creation",
                "state_fips": "06",
                "county_fips": ["019", "031"],
            },
        )
        assert response.status_code == 302
        ws = Workspace.objects.get(name="Fresno Analysis")
        assert ws.db_schema == slugify("Fresno Analysis")
        assert ws.county_fips_list == [
            {"state": "06", "county": "019"},
            {"state": "06", "county": "031"},
        ]

    def test_post_redirects_to_detail(self) -> None:
        """POST should redirect to workspace detail."""
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_create")
        response = self.client.post(
            url,
            {
                "name": "Test Workspace",
                "state_fips": "06",
                "county_fips": ["019"],
            },
        )
        ws = Workspace.objects.get(name="Test Workspace")
        assert response.status_code == 302
        assert response.url == reverse(
            "workspace:workspace_detail", kwargs={"pk": ws.pk}
        )

    def test_post_empty_name(self) -> None:
        """POST with empty name should re-render form with error."""
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_create")
        response = self.client.post(
            url,
            {
                "name": "",
                "state_fips": "06",
                "county_fips": ["019"],
            },
        )
        assert response.status_code == 200
        assert b"error" in response.content.lower()

    def test_post_no_counties(self) -> None:
        """POST with no counties should re-render form with error."""
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_create")
        response = self.client.post(
            url,
            {
                "name": "Fresno Analysis",
                "state_fips": "06",
            },
        )
        assert response.status_code == 200
        assert b"Please select at least one county." in response.content


@pytest.mark.views
class TestWorkspaceDetailView(TestCase):
    """Tests for the workspace detail view."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.workspace = WorkspaceFactory(
            county_fips_list=[
                {"state": "06", "county": "019"},
                {"state": "06", "county": "031"},
            ],
        )

    def test_requires_auth(self) -> None:
        """Unauthenticated GET should redirect."""
        url = reverse("workspace:workspace_detail", kwargs={"pk": self.workspace.pk})
        response = self.client.get(url)
        assert response.status_code == 302

    def test_detail_renders(self) -> None:
        """Authenticated GET should render workspace detail."""
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_detail", kwargs={"pk": self.workspace.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        assert self.workspace.name.encode() in response.content
        assert b"2 counties" in response.content

    def test_data_catalog_present(self) -> None:
        """Data catalog section should be visible."""
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_detail", kwargs={"pk": self.workspace.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        assert b"Data Catalog" in response.content
        assert b"Census ACS" in response.content
        assert b"LEHD Employment" in response.content
        assert b"Parcel Fabric" in response.content

    def test_analysis_catalog_present(self) -> None:
        """Analysis modules section should be visible."""
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_detail", kwargs={"pk": self.workspace.pk})
        response = self.client.get(url)
        assert b"Analysis Modules" in response.content
        assert b"Environmental Constraint" in response.content
        assert b"Core Allocation" in response.content
        assert b"Water Demand" in response.content
        assert b"Energy Demand" in response.content

    def test_quick_actions_present(self) -> None:
        """Quick action buttons should be visible."""
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_detail", kwargs={"pk": self.workspace.pk})
        response = self.client.get(url)
        assert b"View Map" in response.content
        assert b"Import Data" in response.content
        assert b"Run Analysis" in response.content

    def test_region_summary_single_county(self) -> None:
        """Single county workspace shows county name + state."""
        ws = WorkspaceFactory(
            county_fips_list=[{"state": "06", "county": "019"}],
        )
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_detail", kwargs={"pk": ws.pk})
        response = self.client.get(url)
        assert b"Fresno County" in response.content

    def test_empty_county_list_no_crash(self) -> None:
        """Workspace with empty county list should not crash."""
        ws = WorkspaceFactory(county_fips_list=[])
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_detail", kwargs={"pk": ws.pk})
        response = self.client.get(url)
        assert response.status_code == 200

    def test_get_non_existent(self) -> None:
        """GET detail for non-existent PK should return 404."""
        non_existent_pk = Workspace.objects.last().pk + 9999
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_detail", kwargs={"pk": non_existent_pk})
        response = self.client.get(url)
        assert response.status_code == 404


@pytest.mark.views
class TestHomeView(TestCase):
    """Tests for the home page view."""

    def setUp(self) -> None:
        self.user = UserFactory()

    def test_requires_auth(self) -> None:
        """Unauthenticated GET should redirect."""
        url = reverse("workspace:home")
        response = self.client.get(url)
        assert response.status_code == 302

    def test_authenticated_home_renders(self) -> None:
        """Authenticated home should render."""
        self.client.force_login(self.user)
        url = reverse("workspace:home")
        response = self.client.get(url)
        assert response.status_code == 200
        assert b"Create Workspace" in response.content

    def test_workspace_cards_show(self) -> None:
        """Workspaces should appear as cards."""
        ws = WorkspaceFactory(name="Fresno Demo")
        self.client.force_login(self.user)
        url = reverse("workspace:home")
        response = self.client.get(url)
        assert ws.name.encode() in response.content
        assert b"View Map" in response.content
        assert b"Details" in response.content

    def test_create_button_prominent(self) -> None:
        """Create Workspace button should be prominent on home."""
        self.client.force_login(self.user)
        url = reverse("workspace:home")
        response = self.client.get(url)
        assert b"Create Workspace" in response.content
        assert b"btn-primary" in response.content

    def test_empty_workspace_shows_create_prompt(self) -> None:
        """No workspaces should show create prompt."""
        self.client.force_login(self.user)
        url = reverse("workspace:home")
        response = self.client.get(url)
        assert b"Your First Workspace" in response.content


@pytest.mark.views
class TestDataCatalogScoping(TestCase):
    """Tests that data catalog context is properly scoped."""

    def setUp(self) -> None:
        self.user = UserFactory()

    def test_catalog_sources_present_in_context(self) -> None:
        """Data catalog sources should be in context for workspace detail."""
        ws = WorkspaceFactory(county_fips_list=[{"state": "06", "county": "019"}])
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_detail", kwargs={"pk": ws.pk})
        response = self.client.get(url)
        assert b"County Boundary" in response.content
        assert b"Environmental Constraints" in response.content
        assert b"OSM Points of Interest" in response.content

    def test_not_imported_badge(self) -> None:
        """Sources should show 'Not Imported' status by default."""
        ws = WorkspaceFactory(county_fips_list=[{"state": "06", "county": "019"}])
        self.client.force_login(self.user)
        url = reverse("workspace:workspace_detail", kwargs={"pk": ws.pk})
        response = self.client.get(url)
        assert b"Not Imported" in response.content

"""Tests for the static column provenance checker.

Tests the contract resolution layer and provenance checker core
without requiring a running Postgres or dbt manifest.
"""

from __future__ import annotations

from brewgis.workspace.dagster.check_provenance import ProvenanceError
from brewgis.workspace.dagster.check_provenance import resolve_dbt_schema
from brewgis.workspace.dagster.check_provenance import resolve_inline
from brewgis.workspace.dagster.check_provenance import resolve_soda_contract


class TestResolveSodaContract:
    """``resolve_soda_contract`` reads Soda YAML and extracts column names."""

    def test_census_acs(self) -> None:
        """Census ACS contract has 7 columns including ACS variable codes."""
        cols = resolve_soda_contract("census_acs")
        expected = {
            "year",
            "state",
            "county",
            "tract",
            "block_group",
            "b01001_001_e",
            "b25003_001_e",
        }
        assert cols == frozenset(expected), f"Got {sorted(cols)}"

    def test_lehd(self) -> None:
        """LEHD contract has w_geocode, c000, year."""
        cols = resolve_soda_contract("lehd")
        assert "w_geocode" in cols
        assert "c000" in cols
        assert "year" in cols

    def test_poi(self) -> None:
        """POI contract has osm_id, name, category, geometry, lat, lon."""
        cols = resolve_soda_contract("poi")
        assert "osm_id" in cols
        assert "name" in cols
        assert "category" in cols
        assert "geometry" in cols

    def test_nlcd(self) -> None:
        """NLCD contract has geoid, impervious_pct, canopy_pct, land_cover_class."""
        cols = resolve_soda_contract("nlcd")
        assert "geoid" in cols
        assert "impervious_pct" in cols
        assert "canopy_pct" in cols
        assert "land_cover_class" in cols

    def test_spatial_allocation(self) -> None:
        """Spatial allocation contract has target_geoid, source_geoid, etc."""
        cols = resolve_soda_contract("spatial_allocation")
        expected = {
            "target_geoid",
            "source_geoid",
            "allocated_population",
            "allocated_employment",
            "allocation_weight",
        }
        assert cols == frozenset(expected), f"Got {sorted(cols)}"

    def test_column_stitching(self) -> None:
        """Column stitching contract has parcel_id, imputed_* columns."""
        cols = resolve_soda_contract("column_stitching")
        assert "parcel_id" in cols
        assert "imputed_population" in cols
        assert "imputed_households" in cols
        assert "imputed_employment" in cols
        assert "imputed_du" in cols

    def test_built_form_export(self) -> None:
        """Built form export contract has parcel_id, building_type_id, etc."""
        cols = resolve_soda_contract("built_form_export")
        assert "parcel_id" in cols
        assert "building_type_id" in cols
        assert "place_type_id" in cols
        assert "du_per_acre" in cols
        assert "pop_per_acre" in cols
        assert "building_sqft" in cols
        assert "FAR" in cols

    def test_missing_file(self) -> None:
        """Missing contract returns empty set."""
        cols = resolve_soda_contract("nonexistent_contract")
        assert cols == frozenset()


class TestResolveDbtSchema:
    """``resolve_dbt_schema`` reads _schema.yml and returns model columns."""

    def test_core_end_state(self) -> None:
        """core_end_state has parcel_id and gross_acres."""
        cols = resolve_dbt_schema("core_end_state")
        assert "parcel_id" in cols
        assert "gross_acres" in cols

    def test_trip_generation(self) -> None:
        """trip_generation has 8 columns."""
        cols = resolve_dbt_schema("trip_generation")
        expected = {
            "parcel_id",
            "gross_acres",
            "trips_total",
            "trips_res",
            "trips_nonres",
            "trips_hbw",
            "trips_hbo",
            "trips_nhb",
        }
        assert cols == frozenset(expected), f"Got {sorted(cols)}"

    def test_scenario_summary(self) -> None:
        """scenario_summary has scenario_id, population, households, etc."""
        cols = resolve_dbt_schema("scenario_summary")
        assert "scenario_id" in cols
        assert "population" in cols

    def test_missing_model(self) -> None:
        """Unknown model name returns empty set."""
        cols = resolve_dbt_schema("nonexistent_model")
        assert cols == frozenset()


class TestResolveInline:
    """``resolve_inline`` is an identity function."""

    def test_identity(self) -> None:
        """Returns the same frozenset passed in."""
        cols = frozenset({"a", "b", "c"})
        assert resolve_inline(cols) is cols


class TestProvenanceError:
    """``ProvenanceError`` dataclass and helpers."""

    def test_basic_error(self) -> None:
        """ProvenanceError stores all fields."""
        err = ProvenanceError(
            downstream="core_end_state",
            upstream="base_canvas_etl",
            missing=frozenset({"gross_acres"}),
            upstream_source="baseschema",
            downstream_source="dbt:core_end_state",
            suggestion="check renaming",
        )
        assert str(err.downstream) == "core_end_state"
        assert str(err.upstream) == "base_canvas_etl"
        assert err.missing == frozenset({"gross_acres"})
        assert err.upstream_source == "baseschema"
        assert err.downstream_source == "dbt:core_end_state"
        assert err.suggestion == "check renaming"

    def test_minimal_error(self) -> None:
        """ProvenanceError without optional fields."""
        err = ProvenanceError(
            downstream="a",
            upstream="b",
            missing=frozenset({"x"}),
            upstream_source="soda:test",
        )
        assert err.downstream_source is None
        assert err.suggestion is None

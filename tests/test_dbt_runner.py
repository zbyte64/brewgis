"""Tests for the dbt runner module."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import yaml
from django.test import TestCase
from django.test import TransactionTestCase

from brewgis.workspace.analysis.dbt_runner import DbtResult
from brewgis.workspace.analysis.dbt_runner import DbtRunnerWrapper
from brewgis.workspace.analysis.dbt_runner import _build_profiles_yaml
from brewgis.workspace.analysis.dbt_runner import run_dbt_local


@pytest.mark.integration
class TestDbtResult(TestCase):
    """DbtResult construction and attribute access."""

    def test_success_with_results(self) -> None:
        result = DbtResult(
            success=True,
            results=[{"node_name": "model_a", "status": "success"}],
        )
        self.assertTrue(result.success)
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0]["node_name"], "model_a")
        self.assertIsNone(result.error)

    def test_success_with_no_results_defaults_to_empty_list(self) -> None:
        result = DbtResult(success=True)
        self.assertTrue(result.success)
        self.assertEqual(result.results, [])
        self.assertIsNone(result.error)

    def test_success_with_explicit_none_results_defaults_to_empty_list(self) -> None:
        result = DbtResult(success=True, results=None)
        self.assertTrue(result.success)
        self.assertEqual(result.results, [])
        self.assertIsNone(result.error)

    def test_failure_with_error(self) -> None:
        result = DbtResult(success=False, error="Something went wrong")
        self.assertFalse(result.success)
        self.assertEqual(result.results, [])
        self.assertEqual(result.error, "Something went wrong")

    def test_failure_without_error_allows_none(self) -> None:
        result = DbtResult(success=False)
        self.assertFalse(result.success)
        self.assertEqual(result.results, [])
        self.assertIsNone(result.error)


@pytest.mark.integration
class TestBuildProfilesYaml(TestCase):
    """_build_profiles_yaml generates valid YAML from Django DATABASES."""

    db_config_full = {
        "default": {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "HOST": "db.example.com",
            "PORT": "5432",
            "NAME": "brewgis_test",
            "USER": "test_user",
            "PASSWORD": "secret",
        }
    }

    db_config_minimal = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "USER": "test_user",
            "PASSWORD": "",
        }
    }

    db_config_empty_url_fallback = {
        "default": {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "HOST": "",
            "PORT": "",
            "NAME": "",
            "USER": "",
            "PASSWORD": "",
        }
    }

    def test_returns_valid_yaml_with_expected_values(self) -> None:
        with self.settings(DATABASES=self.db_config_full):
            raw = _build_profiles_yaml()
        parsed = yaml.safe_load(raw)

        self.assertIn("brewgis", parsed)
        self.assertIn("outputs", parsed["brewgis"])
        self.assertIn("dev", parsed["brewgis"]["outputs"])
        dev = parsed["brewgis"]["outputs"]["dev"]
        self.assertEqual(dev["type"], "postgres")
        self.assertEqual(dev["host"], "db.example.com")
        self.assertEqual(dev["port"], 5432)
        self.assertEqual(dev["user"], "test_user")
        self.assertEqual(dev["dbname"], "brewgis_test")
        self.assertEqual(dev["pass"], "secret")
        self.assertEqual(dev["schema"], "public")
        self.assertEqual(dev["threads"], 1)

    def test_defaults_when_keys_missing(self) -> None:
        with self.settings(DATABASES=self.db_config_minimal):
            raw = _build_profiles_yaml()
        parsed = yaml.safe_load(raw)
        dev = parsed["brewgis"]["outputs"]["dev"]

        self.assertEqual(dev["host"], "localhost")
        self.assertEqual(dev["port"], 5432)
        self.assertEqual(dev["dbname"], "brewgis")
        self.assertEqual(dev["user"], "test_user")
        self.assertIsNone(dev["pass"])

    def test_falls_back_to_database_url_when_user_empty(self) -> None:
        with (
            self.settings(DATABASES=self.db_config_empty_url_fallback),
            patch(
                "brewgis.workspace.analysis.dbt_runner._env_db_url",
                return_value="postgres://url_user:url_pass@url.host:7777/url_db",
            ),
        ):
            raw = _build_profiles_yaml()
        parsed = yaml.safe_load(raw)
        dev = parsed["brewgis"]["outputs"]["dev"]

        self.assertEqual(dev["host"], "url.host")
        self.assertEqual(dev["port"], 7777)
        self.assertEqual(dev["user"], "url_user")
        self.assertEqual(dev["pass"], "url_pass")
        self.assertEqual(dev["dbname"], "url_db")

    def test_raises_on_unsupported_engine(self) -> None:
        with (
            self.settings(
                DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3"}}
            ),
            self.assertRaises(ValueError, msg="Unsupported database engine for dbt"),
        ):
            _build_profiles_yaml()


@pytest.mark.integration
class TestDbtRunnerWrapperParseResults(TestCase):
    """_parse_results handles various dbtRunner results."""

    def setUp(self) -> None:
        self.runner = DbtRunnerWrapper(project_dir="/tmp/fake_project")

    def test_none_result_attribute_returns_error_result(self) -> None:
        """When result.result is None, returns success=False with str(result)."""
        mock = MagicMock()
        mock.result = None
        result = self.runner._parse_results(mock)
        self.assertFalse(result.success)
        self.assertEqual(result.results, [])

    def test_no_result_attribute_returns_error_result(self) -> None:
        """When result lacks a .result attribute, returns success=False."""
        mock = MagicMock(spec=[])  # no attributes at all
        result = self.runner._parse_results(mock)
        self.assertFalse(result.success)
        self.assertEqual(result.results, [])

    def test_missing_results_artifact_returns_error(self) -> None:
        """When result.result.results is None, returns success=False."""
        inner = MagicMock()
        inner.results = None
        mock = MagicMock()
        mock.result = inner
        result = self.runner._parse_results(mock)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No results artifact in dbt output")

    def test_valid_results_returns_success_with_rows(self) -> None:
        """A well-formed result artifact yields a success DbtResult with row dicts."""
        mock_node = MagicMock()
        mock_node.node_name = "model_a"
        mock_node.status = "success"
        mock_node.timing = "timing_info"
        mock_node.message = "OK"

        inner = MagicMock()
        inner.results = [mock_node]
        mock = MagicMock()
        mock.result = inner

        result = self.runner._parse_results(mock)
        self.assertTrue(result.success)
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0]["node_name"], "model_a")
        self.assertEqual(result.results[0]["status"], "success")

    def test_multiple_results_are_parsed(self) -> None:
        """Multiple nodes in the artifact are all extracted."""
        nodes = []
        for label in ("model_a", "model_b", "model_c"):
            n = MagicMock()
            n.node_name = label
            n.status = "success"
            n.timing = None
            n.message = ""
            nodes.append(n)

        inner = MagicMock()
        inner.results = nodes
        mock = MagicMock()
        mock.result = inner

        result = self.runner._parse_results(mock)
        self.assertTrue(result.success)
        self.assertEqual(len(result.results), 3)
        self.assertEqual(
            [r["node_name"] for r in result.results],
            ["model_a", "model_b", "model_c"],
        )


@pytest.mark.integration
class TestDbtRunnerWrapperRun(TestCase):
    """DbtRunnerWrapper.run() error paths."""

    def test_run_with_nonexistent_project_dir_returns_error(self) -> None:
        """When project_dir does not exist, run returns error DbtResult."""
        runner = DbtRunnerWrapper(project_dir="/nonexistent/path/xyz")
        result = runner.run(select=["env_constraint"])
        self.assertFalse(result.success)
        self.assertIn("dbt project directory not found", result.error)


@pytest.mark.integration
class TestRunDbtLocal(TransactionTestCase):
    """run_dbt_local convenience function."""

    @patch("brewgis.workspace.analysis.dbt_runner.DbtRunnerWrapper")
    def test_delegates_to_runner_run(self, mock_wrapper_cls):
        """run_dbt_local creates a DbtRunnerWrapper and calls run."""
        mock_instance = MagicMock()
        mock_instance.run.return_value = DbtResult(success=True)
        mock_wrapper_cls.return_value = mock_instance

        result = run_dbt_local(
            select=["env_constraint"],
            vars_={"scenario_id": "test_001"},
            full_refresh=True,
        )

        mock_wrapper_cls.assert_called_once_with()
        mock_instance.run.assert_called_once_with(
            select=["env_constraint"],
            vars_={"scenario_id": "test_001"},
            full_refresh=True,
        )
        self.assertTrue(result.success)

    @pytest.mark.integration
    def test_dbt_creates_view_in_target_schema_not_public_prefix(self) -> None:
        """dbt should create views in ``target_schema``, not ``public_target_schema``.

        Creates a test parcel table with geometry, runs dbt against it
        with a custom ``target_schema``, and verifies the view lands
        in that schema (not the profile's ``public`` schema).
        """
        from django.db import connection

        target_schema = "test_dbt_schema_check"
        parcel_table = "test_dbt_parcels"

        with connection.cursor() as cursor:
            # Ensure PostGIS ext
            cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            # Create source schema and test parcel table
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {target_schema}")
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {parcel_table} (
                    id SERIAL PRIMARY KEY,
                    geom GEOMETRY(POLYGON, 4326)
                )
            """)
            cursor.execute(f"""
                INSERT INTO {parcel_table} (geom)
                VALUES (ST_SetSRID(ST_MakeEnvelope(0, 0, 1, 1), 4326))
            """)

        try:
            result = run_dbt_local(
                select=["env_constraint"],
                vars_={
                    "target_schema": target_schema,
                    "scenario_id": "test_dbt_schema",
                    "parcel_table": parcel_table,
                    "constraints": [],
                    "source_schema": "public",
                },
                full_refresh=True,
            )
            assert result.success, f"dbt run failed: {result.error}"

            # Check individual model results
            for row in result.results or []:
                assert row["status"] in ("success", "pass"), (
                    f"Model {row['node_name']} failed: {row['message']}"
                )

            # The view should be created in target_schema, NOT public_target_schema.
            # The view name equals the model file name (env_constraint).
            view_name = "env_constraint"
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.views
                        WHERE table_schema = %s
                        AND table_name = %s
                    )
                    """,
                    [target_schema, view_name],
                )
                exists_in_target = cursor.fetchone()[0]
            assert exists_in_target, (
                f"View '{view_name}' not found in schema '{target_schema}'"
            )

            # Also verify it does NOT exist in a public_ prefix schema
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.views
                        WHERE table_schema = %s
                        AND table_name = %s
                    )
                    """,
                    [f"public_{target_schema}", view_name],
                )
                exists_in_public_prefix = cursor.fetchone()[0]
            assert not exists_in_public_prefix, (
                f"View should NOT exist in 'public_{target_schema}' schema"
            )
        finally:
            # Cleanup: drop the view and test schema
            with connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS {parcel_table} CASCADE")
                cursor.execute(f"DROP SCHEMA IF EXISTS {target_schema} CASCADE")

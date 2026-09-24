"""Fixtures for the SQLMesh parity tests.

The analysis models under ``brewgis/sqlmesh/models/analysis/**`` are
*blueprinted*: SQLMesh renders one instance per analyzed scenario, named from
the rows ``sqlmesh/macros/analysis_blueprints.py`` reads out of the database.
A blueprinted model with an empty ``blueprints`` list does not load at all
("Failed to render blueprints property"), so a test database with no analyzed
scenario cannot load the project — hence this fixture.
"""

from __future__ import annotations

import pytest
from django.db import connection

from brewgis.workspace.models import ScenarioType
from tests.factories import AnalysisRunFactory
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory


@pytest.fixture(scope="session")
def sqlmesh_test_database(django_db_setup) -> None:
    """Point SQLMesh's gateways at the test database for the whole session.

    ``brewgis/sqlmesh/config.py`` parses ``DATABASE_URL`` into ``_db_kwargs`` at
    *import* time, and ``/app/.env`` pins that to the live ``brewgis`` database —
    while pytest-django switches Django (and any raw psycopg connection built
    from ``settings.DATABASES``) to ``test_brewgis``. Without this, a parity run
    writes its synthetic upstream tables into the test database while SQLMesh
    plans and materializes into the live one, and fails with
    ``relation "<empty schema>.<table>" does not exist`` — having mutated the
    developer's database on the way.

    The config module is re-pointed (rather than the environment) because
    ``config_factory`` reads its globals at call time, and the change has to
    exist *before* SQLMesh forks its model-loading workers: a forked child
    inherits it. The models keep their ``brewgis`` catalog — the config maps it
    onto whatever the database is named.

    The session starts from no SQLMesh state (see ``reset_sqlmesh_state``).
    """
    from django.conf import settings

    from brewgis.sqlmesh import config as sqlmesh_config
    from tests.dbt_math.sqlmesh_model_runner import reset_sqlmesh_state

    previous = sqlmesh_config.use_database(settings.DATABASES["default"]["NAME"])
    reset_sqlmesh_state()
    yield
    sqlmesh_config.use_database(previous)


@pytest.fixture
def parity_scenario(sqlmesh_test_database, django_db_blocker) -> str:
    """Create the scenarios a parity run's model load needs; return the schema.

    Committed (not part of the test's transaction) because SQLMesh loads models
    in forked workers whose own connections cannot see uncommitted rows. Run
    these tests with ``django_db(transaction=True)`` so the rows are flushed
    afterwards.

    Two rows are needed, one per blueprint provider:

    * a scenario with an ``AnalysisRun`` on a SQLMesh-managed base table — the
      analysis models' profile, which also supplies the ``ascn<scenario_pk>``
      schema the run materializes in;
    * an ALTERNATIVE scenario on the published ``public.base_canvas``, so
      ``scenario_canvas`` has one blueprint too (it is the other blueprinted
      model, and the project does not load without one).
    """
    with django_db_blocker.unblock():
        canvas_workspace = WorkspaceFactory(base_table="public.base_canvas")
        ScenarioFactory(
            workspace=canvas_workspace, scenario_type=ScenarioType.ALTERNATIVE
        )
        workspace = WorkspaceFactory(base_table="fresno.base_canvas_reconciled")
        scenario = ScenarioFactory(workspace=workspace)
        AnalysisRunFactory(workspace=workspace, scenario=scenario)
        connection.commit()

    return f"ascn{scenario.pk}"

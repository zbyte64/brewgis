"""Shared plumbing for the live-stack integration tests.

``test_map_render_parity.py`` and ``test_paint_live_refresh.py`` drive the real
dev stack, so they cannot use pytest-django's test database: Martin and tipg
read the dev database directly, so seeding data through ``test_brewgis`` would
be invisible to them. Each therefore creates its own workspace over a plain
psycopg connection and has to remove it afterwards.

That teardown is the problem this module solves. Every foreign key pointing at
a workspace, layer, scenario or symbology config is ``NO ACTION``
(``confdeltype = 'a'``), so a single ``DELETE FROM workspace_workspace`` fails
on the first child table PostgreSQL happens to check — and the rows the *page
render* creates (the painted-features overlay layer and its auto-generated
symbology) are not in the ids the fixture returned. Deleting children first,
scoped by workspace, removes exactly the fixture's own rows: a real workspace
and its layers are untouched by construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg import sql

if TYPE_CHECKING:
    import psycopg

# Children first, and the parents they hang off of last (scenario before
# workspace). Statements are of three shapes:
#
#   workspace-scoped   — ``workspace_id`` is a column on the table itself
#   layer-scoped       — layer filter / symbology config / style class, which
#                        only know their layer (or their symbology config)
#   scenario-scoped    — paint and geometry-edit rows, which only know their
#                        scenario
#
# Every one is scoped to the fixture's own workspace id, so this cannot touch a
# real workspace's data. Written out rather than composed: a query string built
# by interpolation is exactly what S608 exists to catch.
_WORKSPACE_CHILD_DELETES: tuple[str, ...] = (
    (
        "DELETE FROM workspace_layerfilter WHERE layer_id IN ("
        "SELECT id FROM workspace_layer WHERE workspace_id = %s)"
    ),
    (
        "DELETE FROM workspace_styleclass WHERE symbology_id IN ("
        "SELECT id FROM workspace_symbologyconfig WHERE layer_id IN ("
        "SELECT id FROM workspace_layer WHERE workspace_id = %s))"
    ),
    (
        "DELETE FROM workspace_symbologyconfig WHERE layer_id IN ("
        "SELECT id FROM workspace_layer WHERE workspace_id = %s)"
    ),
    (
        "DELETE FROM workspace_paintedcanvas WHERE scenario_id IN ("
        "SELECT id FROM workspace_scenario WHERE workspace_id = %s)"
    ),
    (
        "DELETE FROM workspace_paintevent WHERE scenario_id IN ("
        "SELECT id FROM workspace_scenario WHERE workspace_id = %s)"
    ),
    (
        "DELETE FROM workspace_parcelgeometryedit WHERE scenario_id IN ("
        "SELECT id FROM workspace_scenario WHERE workspace_id = %s)"
    ),
    "DELETE FROM workspace_layer WHERE workspace_id = %s",
    "DELETE FROM workspace_layergroup WHERE workspace_id = %s",
    "DELETE FROM workspace_paintconstraint WHERE workspace_id = %s",
    "DELETE FROM workspace_dataimportrun WHERE workspace_id = %s",
    "DELETE FROM workspace_buildingtype WHERE workspace_id = %s",
    "DELETE FROM workspace_placetype WHERE workspace_id = %s",
    "DELETE FROM workspace_poicache WHERE workspace_id = %s",
    "DELETE FROM workspace_externalmapservice WHERE workspace_id = %s",
    "DELETE FROM workspace_mergeaudit WHERE workspace_id = %s",
    "DELETE FROM workspace_paintrun WHERE workspace_id = %s",
    "DELETE FROM workspace_analysisrun WHERE workspace_id = %s",
    "DELETE FROM workspace_scenarioreport WHERE workspace_id = %s",
    "DELETE FROM workspace_scenario WHERE workspace_id = %s",
    "DELETE FROM workspace_workspace WHERE id = %s",
)


def delete_workspace_rows(conn: psycopg.Connection, workspace_id: int) -> None:
    """Delete a fixture workspace: every row that references it, then itself."""
    with conn.cursor() as cur:
        for statement in _WORKSPACE_CHILD_DELETES:
            cur.execute(sql.SQL(statement), (workspace_id,) * statement.count("%s"))
    conn.commit()


# Six workspace tables reference ``auth_user`` without a cascade, so a plain
# ``DELETE FROM auth_user`` aborts while any of them still points at the user.
# Normally the workspace delete above has already taken them, but a run that
# died before teardown leaves rows behind — and then *every* later run fails to
# clean up its user. Scoped by username, which only these fixtures create.
_USER_CHILD_DELETES: tuple[str, ...] = (
    (
        "DELETE FROM workspace_paintrun WHERE created_by_id IN ("
        "SELECT id FROM auth_user WHERE username = %s)"
    ),
    (
        "DELETE FROM workspace_paintevent WHERE painted_by_id IN ("
        "SELECT id FROM auth_user WHERE username = %s)"
    ),
    (
        "DELETE FROM workspace_paintedcanvas WHERE painted_by_id IN ("
        "SELECT id FROM auth_user WHERE username = %s)"
    ),
    (
        "DELETE FROM workspace_parcelgeometryedit WHERE created_by_id IN ("
        "SELECT id FROM auth_user WHERE username = %s)"
    ),
    (
        "DELETE FROM workspace_mergeaudit WHERE performed_by_id IN ("
        "SELECT id FROM auth_user WHERE username = %s)"
    ),
    (
        "DELETE FROM workspace_scenarioreport WHERE created_by_id IN ("
        "SELECT id FROM auth_user WHERE username = %s)"
    ),
    (
        "DELETE FROM auth_user_groups WHERE user_id IN ("
        "SELECT id FROM auth_user WHERE username = %s)"
    ),
    (
        "DELETE FROM auth_user_user_permissions WHERE user_id IN ("
        "SELECT id FROM auth_user WHERE username = %s)"
    ),
    (
        "DELETE FROM django_admin_log WHERE user_id IN ("
        "SELECT id FROM auth_user WHERE username = %s)"
    ),
    (
        "DELETE FROM account_emailaddress WHERE user_id IN ("
        "SELECT id FROM auth_user WHERE username = %s)"
    ),
    "DELETE FROM auth_user WHERE username = %s",
)


def delete_user_rows(conn: psycopg.Connection, username: str) -> None:
    """Delete a fixture user, after the rows that reference it."""
    with conn.cursor() as cur:
        for statement in _USER_CHILD_DELETES:
            cur.execute(sql.SQL(statement), (username,) * statement.count("%s"))
    conn.commit()

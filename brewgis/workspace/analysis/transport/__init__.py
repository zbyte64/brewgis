"""Transport analysis pure-function re-exports.

The gravity model's math lives in
``brewgis/sqlmesh/models/python/_gravity_model.py`` — a module with no
blueprint machinery, so a unit test can import it without a database — and is
re-exported here for test use.

Mode choice is a blueprinted SQL model
(``brewgis/sqlmesh/models/analysis/transport/mode_choice.sql``), not a Python
function, and the SQLMesh model that runs this gravity model
(``brewgis/sqlmesh/models/python/trip_distribution.py``) is deliberately not
imported here: importing it reads the scenario profiles from the database.
"""

from __future__ import annotations

from brewgis.sqlmesh.models.python._gravity_model import _gravity_model

__all__ = ["_gravity_model"]

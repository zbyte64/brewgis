"""``ensure_martin_source`` — the two ways Martin's tiles go stale.

Martin renders tiles from the database but keeps them: its cache is keyed by
``(source, z, x, y)`` and never looks at the request, and it learns which tables
exist only by scanning the database once at startup. So a rewritten view
(``built_form_fill.fill_<pk>`` after a fill re-run) needs its cache dropped, and
a view Martin has never seen (the same view, the first time the fill is turned
on) needs the restart. Picking the wrong one silently leaves the map drawing
data the database no longer holds, which is the failure this pins.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings

from brewgis.workspace.services import tile_server

if TYPE_CHECKING:
    import pytest


def _stub_http(
    monkeypatch: pytest.MonkeyPatch, published: set[str] | None
) -> tuple[list[str], list[str]]:
    """Stub Martin's HTTP surface; return (deleted urls, restarted reasons)."""
    deletes: list[str] = []
    restarts: list[str] = []

    def fake_delete(url: str, **kwargs: Any) -> Any:
        deletes.append(url)
        return SimpleNamespace(status_code=200, ok=True, text="")

    def fake_restart() -> bool:
        restarts.append("restart")
        return True

    monkeypatch.setattr(tile_server, "martin_source_ids", lambda: published)
    monkeypatch.setattr(tile_server.requests, "delete", fake_delete)
    monkeypatch.setattr(tile_server, "restart_martin", fake_restart)
    return deletes, restarts


def test_a_published_source_is_purged_without_restarting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "built_form_fill.fill_78"
    deletes, restarts = _stub_http(monkeypatch, published={source, "other.table"})

    assert tile_server.ensure_martin_source(source) is True

    assert deletes == [f"{settings.TILE_SERVER_MARTIN_URL}/cache/{source}"]
    assert restarts == []


def test_an_unpublished_source_restarts_martin_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Martin can't purge what it never discovered — a restart is the only way.

    The restart re-scans the database (so the source exists at all) and drops
    every cached tile with it, which is why no purge is needed alongside.
    """
    source = "built_form_fill.fill_9"
    deletes, restarts = _stub_http(monkeypatch, published={"other.table"})
    waited: list[list[str]] = []

    def fake_wait(fqtns: list[str]) -> bool:
        waited.append(list(fqtns))
        return True

    monkeypatch.setattr(tile_server, "wait_until_martin_ready", fake_wait)

    assert tile_server.ensure_martin_source(source) is True

    assert restarts == ["restart"]
    assert waited == [[source]]
    assert deletes == []


def test_an_unreachable_martin_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No catalog, no action: guessing at a broken container isn't an improvement."""
    deletes, restarts = _stub_http(monkeypatch, published=None)

    assert tile_server.ensure_martin_source("built_form_fill.fill_78") is False

    assert deletes == []
    assert restarts == []

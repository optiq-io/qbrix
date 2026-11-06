"""integration tests for the workspace's status, a qbrix next surface.

invariants verified:
  one read returns the version, whether each service answers, and how far
  learning trails the ledger. learning is behind when cortex left no progress
  or trails past the limit. with next off the route doesn't exist.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest_asyncio

import proxysvc.config
from qbrixstore.redis.health import LedgerProgress

from proxysvc.mod.status import LEARNING_BEHIND_MS
from proxysvc.mod.status import VERSION
from proxysvc.next import next_routes

CHECKED_MS = 1_700_000_000_000


@pytest_asyncio.fixture
async def api(wired_app, client, next_enabled):
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    yield client
    app.router.routes[:] = routes


async def _progress(wired_app, lag_ms: int) -> None:
    await wired_app.svc.redis.set_ledger_progress(
        LedgerProgress(
            complete_up_to_ms=CHECKED_MS - lag_ms, lag_ms=lag_ms, checked_ms=CHECKED_MS
        )
    )


async def _status(api) -> dict:
    resp = await api.get("/api/v1/runtime/status")
    assert resp.status_code == 200
    return resp.json()


async def test_a_running_workspace_answers_and_keeps_up(wired_app, api):
    await _progress(wired_app, lag_ms=4_000)

    body = await _status(api)

    assert body == {
        "version": VERSION,
        "services": {"storage": True, "deciding": True, "learning": True},
        "learning": {
            "lag_ms": 4_000,
            "checked_at": "2023-11-14T22:13:20+00:00",
            "behind": False,
        },
    }


async def test_a_service_that_doesnt_answer_says_so(wired_app, api):
    await _progress(wired_app, lag_ms=0)
    wired_app.svc._cortex_client.health = AsyncMock(return_value=False)

    body = await _status(api)

    assert body["services"] == {"storage": True, "deciding": True, "learning": False}


async def test_learning_is_behind_past_the_limit(wired_app, api):
    await _progress(wired_app, lag_ms=LEARNING_BEHIND_MS + 1)

    assert (await _status(api))["learning"]["behind"] is True


async def test_learning_is_behind_when_cortex_left_no_progress(api):
    body = await _status(api)

    assert body["learning"] == {"lag_ms": None, "checked_at": None, "behind": True}


async def test_without_next_the_route_doesnt_exist(wired_app, client):
    resp = await client.get("/api/v1/runtime/status")

    assert resp.status_code == 404

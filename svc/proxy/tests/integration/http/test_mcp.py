"""integration tests for qbrix's mcp server at /mcp, a qbrix next surface.

invariants verified:
  only a connection's access token reaches the tools: no token, a key, a
  revoked connection's token and a token for another resource each get 401
  pointing at the protected resource metadata, and an exhausted limit gets
  429 with when to retry. clients on 2026-07-28 and on 2025-11-25 list and
  call the tools, in a fixed order, and any replica answers any call. a
  change records who, via which client and why, and its result names the
  change, whether it can be undone and its console link. a repeated change
  within the window changes nothing twice. change_get reads one change of
  this workspace, by anyone, with its status, and no other workspace's. a
  change that asks first is put to its person in a client that can ask, on
  any replica: approved, declined with or without a reason, or left waiting
  when the question is closed; an answer is taken once, only for its own
  call and connection, and doesn't count as a second change. a
  viewer's connection reads and can't change. a loop paused by qbrix says who paused it, when and why, in
  loop_get and loops_list. workspace_summary reads the same as the service,
  in product words, an open safety pause first. delivery_update changes who
  a loop decides for, says so in one line that loop_get repeats, waits when
  it asks first and applies when approved. every refusal says what to do
  next.
"""

from __future__ import annotations

import asyncio
import itertools
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
import pytest_asyncio
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import ElicitResult
from mcp_types import InputRequiredResult
from starlette.applications import Starlette
from starlette.routing import Route

import proxysvc.config
from qbrixstore.event import MilestoneEvent
from qbrixstore.postgres import session as session_module
from qbrixstore.postgres.models import Tenant
from qbrixstore.postgres.models import User

from proxysvc.core.actor import Actor
from proxysvc.next import next_routes
from proxysvc.transport.mcp.server import MCP_PATH
from proxysvc.transport.mcp.server import build_mcp

TENANT = "tenant-a"
MODERN = "2026-07-28"
LEGACY = "legacy"

PEOPLE = {
    "user-member": ("member", "Mustafa"),
    "user-viewer": ("viewer", "Vera"),
}

TOOLS = [
    "loops_list",
    "loop_get",
    "loop_results",
    "metrics_list",
    "changes_list",
    "change_get",
    "loop_history",
    "milestones_list",
    "workspace_summary",
    "loop_create",
    "loop_rename",
    "loop_launch",
    "loop_commit",
    "loop_reopen",
    "loop_retire",
    "loop_pause",
    "loop_resume",
    "cycle_start",
    "cycle_reset",
    "delivery_update",
    "context_update",
    "metric_create",
    "note_add",
    "change_undo",
]

LOOP = {
    "name": "Checkout headline",
    "metric": "purchase",
    "options": [
        {"name": "Control", "config": {"headline": "Buy now"}},
        {"name": "Urgency", "config": {"headline": "Only 3 left"}},
    ],
    "reason": "test which headline sells",
}

EVIDENCE = {
    "signal": "decision_errors",
    "rate": 0.238,
    "errors": 150,
    "calls": 629,
    "window_start": "2026-10-27T09:51:00+00:00",
    "window_end": "2026-10-27T10:00:12+00:00",
    "reasons": {"motor_unavailable": 150},
}

METRIC = {
    "name": "purchase",
    "semantic": "a completed checkout",
    "type": "conversion",
    "reason": "loops on checkout need it",
}


@pytest_asyncio.fixture
async def mcp(wired_app, next_enabled):
    """the app with the next routes mounted and the mcp server running, and a
    workspace with a member and a viewer."""
    async with session_module.get_session() as session:
        session.add(Tenant(id=TENANT, name=TENANT, slug=TENANT))
        for user_id, (role, name) in PEOPLE.items():
            session.add(
                User(
                    id=user_id,
                    tenant_id=TENANT,
                    email=f"{user_id}@example.com",
                    password_hash="x",
                    name=name,
                    role=role,
                )
            )

    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    stop = await _hold(app.state.mcp)
    yield app
    await stop()
    app.router.routes[:] = routes
    del app.state.mcp


async def _hold(server):
    """runs a server's session manager in a task of its own: a fixture sets up
    and tears down in different tasks, and the manager's task group must exit
    in the task that entered it."""
    running = asyncio.Event()
    stopping = asyncio.Event()

    async def hold():
        async with server.session_manager.run():
            running.set()
            await stopping.wait()

    task = asyncio.create_task(hold())
    await running.wait()

    async def stop():
        stopping.set()
        await task

    return stop


async def _token(
    wired_app,
    user: str = "user-member",
    *,
    client: str = "Claude Code",
    resource: str | None = None,
) -> str:
    issued = await wired_app.svc.connections.open(
        user_id=user,
        tenant_id=TENANT,
        client_identity=f"{client}:{user}",
        client_id=f"client-{client}",
        client_name=client,
        client_uri=None,
        resource=resource or wired_app.svc._settings.mcp_resource,
    )
    return issued.access_token


def _http(app, token: str | None) -> httpx2.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://test",
        headers=headers,
    )


@asynccontextmanager
async def _connect(
    http: httpx2.AsyncClient, mode: str = MODERN, answer=None
) -> AsyncIterator[Client]:
    """a client; with answer, one that can ask its person and answers so."""
    async with (
        http,
        Client(
            streamable_http_client(f"http://test{MCP_PATH}", http_client=http),
            mode=mode,
            elicitation_callback=answer,
        ) as client,
    ):
        yield client


ON_ITS_OWN = {"loop.launch": "own", "cycle.start": "own", "loop.retire": "own"}


@asynccontextmanager
async def _session(
    app, wired_app, user="user-member", mode=MODERN, levels=ON_ITS_OWN, answer=None
):
    """a connected client. its person lets it make every change on its own,
    so a tool's own result is what a test sees; tests about asking first pass
    levels=None for the defaults."""
    token = await _token(wired_app, user)
    if levels:
        [connection] = [
            connection
            for connection in await wired_app.svc.connections.list(
                TENANT, user_id=user, role=PEOPLE[user][0]
            )
            if connection["client"]["name"] == "Claude Code"
        ]
        await wired_app.svc.connections.set_levels(
            TENANT,
            connection["id"],
            levels,
            actor=Actor.member(user),
            role=PEOPLE[user][0],
        )
    async with _connect(_http(app, token), mode, answer) as client:
        yield client


async def _call(client: Client, tool: str, arguments: dict[str, Any] | None = None):
    return await client.call_tool(tool, arguments or {})


def _error(result) -> str:
    assert result.is_error, result
    return result.content[0].text


async def _post(app, token: str | None):
    async with _http(app, token) as http:
        return await http.post(
            MCP_PATH,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )


async def _draft(client: Client) -> dict:
    await _call(client, "metric_create", METRIC)
    result = await _call(client, "loop_create", LOOP)
    assert not result.is_error, result
    return result.structured_content


class TestSigningIn:

    async def test_no_token_points_at_the_resource_metadata(self, mcp):
        response = await _post(mcp, None)

        origin = proxysvc.config.settings.public_origin
        assert response.status_code == 401
        assert (
            f'resource_metadata="{origin}/.well-known/oauth-protected-resource/mcp"'
            in response.headers["www-authenticate"]
        )

    async def test_the_metadata_names_qbrix_and_the_mcp_resource(self, mcp):
        settings = proxysvc.config.settings
        async with _http(mcp, None) as http:
            response = await http.get("/.well-known/oauth-protected-resource/mcp")

        assert response.status_code == 200
        body = response.json()
        assert body["resource"] == settings.mcp_resource
        assert body["authorization_servers"] == [settings.public_origin]

    @pytest.mark.parametrize(
        "token",
        ["optiq_a_key_for_the_request_path", "qbx_at_unknown", "not-a-token"],
    )
    async def test_anything_but_a_connection_token_is_refused(self, mcp, token):
        response = await _post(mcp, token)

        assert response.status_code == 401
        assert "resource_metadata=" in response.headers["www-authenticate"]

    async def test_a_revoked_connection_is_refused(self, mcp, wired_app):
        token = await _token(wired_app)
        principal = await wired_app.svc.connections.authenticate(token)
        await wired_app.svc.connections.revoke(
            TENANT,
            principal.actor.connection_id,
            user_id="user-member",
            role="member",
        )

        assert (await _post(mcp, token)).status_code == 401

    async def test_a_token_for_another_resource_is_refused(self, mcp, wired_app):
        token = await _token(wired_app, resource="https://elsewhere.example/mcp")

        assert (await _post(mcp, token)).status_code == 401

    async def test_an_exhausted_limit_says_when_to_retry(
        self, mcp, wired_app, monkeypatch
    ):
        monkeypatch.setattr(wired_app.svc._settings, "mcp_calls_per_minute", 1)
        token = await _token(wired_app)
        await _post(mcp, token)

        response = await _post(mcp, token)

        assert response.status_code == 429
        assert 0 < int(response.headers["retry-after"]) <= 60
        assert "Try again in" in response.json()["error_description"]
        cursor = await _token(wired_app, client="Cursor")
        assert (await _post(mcp, cursor)).status_code == 200


class TestProtocol:

    @pytest.mark.parametrize("mode", [MODERN, LEGACY])
    async def test_both_versions_list_and_call(self, mcp, wired_app, mode):
        async with _session(mcp, wired_app, mode=mode) as client:
            tools = await client.list_tools()
            result = await _call(client, "metric_create", METRIC)

        assert [tool.name for tool in tools.tools] == TOOLS
        assert not result.is_error
        assert result.structured_content["metric"]["name"] == "purchase"

    async def test_the_tool_list_may_be_cached_for_an_hour(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            tools = await client.list_tools(cache_mode="refresh")

        assert tools.ttl_ms == 3_600_000

    async def test_reads_are_marked_read_only_and_launch_destructive(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}

        for name in (
            "loops_list",
            "loop_get",
            "loop_results",
            "metrics_list",
            "change_get",
        ):
            assert tools[name].annotations.read_only_hint is True
        assert tools["loop_launch"].annotations.destructive_hint is True
        assert tools["loop_rename"].annotations.destructive_hint is True
        assert tools["loop_create"].annotations.destructive_hint is False
        assert tools["loop_create"].output_schema is not None

    @pytest.mark.parametrize("mode", [MODERN, LEGACY])
    async def test_any_replica_answers_any_call(self, mcp, wired_app, mode):
        replicas = []
        for _ in range(2):
            server, asgi = build_mcp(proxysvc.config.settings)
            replicas.append((server, Starlette(routes=[Route(MCP_PATH, asgi)])))
        transport = _RoundRobin(
            [httpx2.ASGITransport(app=replica) for _, replica in replicas]
        )
        token = await _token(wired_app)
        http = httpx2.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        )

        async with replicas[0][0].session_manager.run():
            async with replicas[1][0].session_manager.run():
                async with _connect(http, mode) as client:
                    await _call(client, "metric_create", METRIC)
                    created = await _call(client, "loop_create", LOOP)
                    listed = await _call(client, "loops_list")

        assert not created.is_error
        assert [loop["key"] for loop in listed.structured_content["loops"]] == [
            "checkout-headline"
        ]
        assert transport.served == {0, 1}


class _RoundRobin(httpx2.AsyncBaseTransport):
    """hands each request to the next replica in turn."""

    def __init__(self, transports: list[httpx2.ASGITransport]):
        self._next = itertools.cycle(enumerate(transports))
        self.served: set[int] = set()

    async def handle_async_request(self, request):
        index, transport = next(self._next)
        self.served.add(index)
        return await transport.handle_async_request(request)


class TestChanges:

    async def test_create_then_launch_records_who_via_and_why(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            draft = await _draft(client)
            launched = await _call(
                client,
                "loop_launch",
                {"loop": "checkout-headline", "reason": "the select call is merged"},
            )

        assert draft["status"] == "applied"
        assert draft["change"]["kind"] == "loop.create"
        assert draft["change"]["undoable"] is True
        assert draft["change"]["url"] == (
            f"{proxysvc.config.settings.console_origin}/loops/checkout-headline"
            f"/history?change={draft['change']['id']}"
        )
        assert draft["loop"]["state"] == "draft"

        change = launched.structured_content["change"]
        assert change["kind"] == "loop.launch"
        assert change["undoable"] is False
        assert launched.structured_content["loop"]["state"] == "live"

        history = await wired_app.svc.loop_history(
            TENANT, "checkout-headline", limit=10
        )
        entries = {entry["kind"]: entry for entry in history["changes"]}
        for kind, reason in (
            ("loop.create", LOOP["reason"]),
            ("loop.launch", "the select call is merged"),
        ):
            entry = entries[kind]
            assert entry["who"]["name"] == "Mustafa"
            assert entry["via"]["client"] == "Claude Code"
            assert entry["reason"] == reason
            assert entry["request_id"]

    async def test_metric_create_links_to_the_metric(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            result = await _call(client, "metric_create", METRIC)

        change = result.structured_content["change"]
        assert change["kind"] == "metric.create"
        assert change["url"] == (
            f"{proxysvc.config.settings.console_origin}/metrics/purchase"
            f"?change={change['id']}"
        )

    async def test_a_repeated_call_changes_nothing_twice(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            first = await _draft(client)
            second = await _call(client, "loop_create", LOOP)

        assert second.structured_content == first
        page = await wired_app.svc.list_loops(TENANT, limit=10)
        assert len(page["loops"]) == 1

    async def test_the_same_call_with_another_reason_is_a_new_call(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            again = await _call(client, "loop_create", {**LOOP, "reason": "again"})

        page = await wired_app.svc.list_loops(TENANT, limit=10)
        assert not again.is_error
        assert len(page["loops"]) == 2

    async def test_a_refused_call_runs_again_once_fixed(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            refused = await _call(client, "loop_create", LOOP)
            await _call(client, "metric_create", METRIC)
            retried = await _call(client, "loop_create", LOOP)

        assert refused.is_error
        assert not retried.is_error


class TestChangeLimit:
    @pytest.fixture(autouse=True)
    def mid_minute(self, monkeypatch):
        """caps count per clock minute; a test straddling one would reset."""
        now = int(time.time()) // 60 * 60 + 30
        monkeypatch.setattr(
            "proxysvc.mod.connection.service.time", SimpleNamespace(time=lambda: now)
        )

    async def test_a_change_over_the_cap_applies_nothing_and_reads_still_work(
        self, mcp, wired_app, monkeypatch
    ):
        monkeypatch.setattr(wired_app.svc._settings, "mcp_changes_per_minute", 1)
        async with _session(mcp, wired_app) as client:
            await _call(client, "metric_create", METRIC)
            refused = await _call(client, "loop_create", LOOP)
            read = await _call(client, "metrics_list")

        message = _error(refused)
        assert message.startswith("This connection made 1 changes this minute.")
        assert "nothing was applied" in message
        assert int(message.split("Try again in ")[1].split(" ")[0]) in range(1, 61)
        assert not read.is_error
        assert (await wired_app.svc.list_loops(TENANT, limit=10))["loops"] == []

    async def test_a_repeated_change_counts(self, mcp, wired_app, monkeypatch):
        monkeypatch.setattr(wired_app.svc._settings, "mcp_changes_per_minute", 2)
        async with _session(mcp, wired_app) as client:
            first = await _call(client, "metric_create", METRIC)
            repeat = await _call(client, "metric_create", METRIC)
            refused = await _call(client, "loop_create", LOOP)

        assert repeat.structured_content == first.structured_content
        assert "changes this minute" in _error(refused)

    async def test_each_connection_has_its_own_cap(self, mcp, wired_app, monkeypatch):
        monkeypatch.setattr(wired_app.svc._settings, "mcp_changes_per_minute", 1)
        cursor = await _token(wired_app, client="Cursor")
        async with _session(mcp, wired_app) as client:
            await _call(client, "metric_create", METRIC)
            refused = await _call(client, "loop_create", LOOP)
        async with _connect(_http(mcp, cursor)) as client:
            created = await _call(client, "loop_create", LOOP)

        assert refused.is_error
        assert not created.is_error


class TestChangesAndUndo:

    async def test_changes_list_says_who_what_and_why(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            draft = await _draft(client)
            result = await _call(client, "changes_list", {"kind": ["loop.create"]})

        assert not result.is_error, result
        entry = result.structured_content["changes"][0]
        assert entry["id"] == draft["change"]["id"]
        assert entry["via"]["client"] == entry["pieces"][0]["actor"]["name"]
        assert entry["target"]["key"] == "checkout-headline"
        line = result.content[0].text
        client_name = entry["via"]["client"]
        assert f"{client_name} created Checkout headline." in line
        assert f"Mustafa via {client_name}" in line
        assert '"test which headline sells"' in line
        assert "can be undone" in line

    async def test_changes_list_says_why_qbrix_paused(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            await _call(
                client, "loop_launch", {"loop": "checkout-headline", "reason": "go"}
            )
            await wired_app.svc.loops.pause_loop(
                TENANT, "checkout-headline", actor=Actor.qbrix(), evidence=EVIDENCE
            )
            result = await _call(client, "changes_list", {"who": ["qbrix"]})

        line = result.content[0].text
        assert "qbrix paused Checkout headline." in line
        assert "state live -> paused" in line
        assert "decision errors 23.8% of 629 calls" in line

    async def test_changes_list_reads_the_same_as_http(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(client, "changes_list")

        page = await wired_app.svc.list_workspace_changes(TENANT, limit=20)
        assert [entry["id"] for entry in result.structured_content["changes"]] == [
            entry["id"] for entry in page["changes"]
        ]

    async def test_milestones_list_reads_the_same_as_http(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            loop = (await _draft(client))["loop"]
            wired_app.ledger.reach(
                MilestoneEvent(
                    event_id=f"first_call:{loop['id']}",
                    kind="loop.first_call",
                    tenant_id=TENANT,
                    loop_id=loop["id"],
                    cycle_id="",
                    payload={"source": "web-prod"},
                    at_ms=1_700_000_000_000,
                )
            )
            result = await _call(client, "milestones_list", {"loop": loop["key"]})

        found = await wired_app.svc.list_milestones(TENANT, limit=20)
        assert [e["id"] for e in result.structured_content["milestones"]] == [
            e["id"] for e in found["milestones"]
        ]
        assert "web-prod made the first call to Checkout headline." in (
            result.content[0].text
        )

    async def test_milestones_list_refuses_an_unknown_loop(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            result = await _call(client, "milestones_list", {"loop": "nope"})

        assert result.is_error

    async def test_changes_list_filters_and_refuses_an_unknown_loop(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            metric = await _call(client, "changes_list", {"metric": "purchase"})
            unknown = await _call(client, "changes_list", {"loop": "checkout-hedline"})

        kinds = [entry["kind"] for entry in metric.structured_content["changes"]]
        assert kinds == ["metric.create"]
        assert "Did you mean checkout-headline?" in _error(unknown)

    async def test_an_undo_is_recorded_as_the_person_via_the_client(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            draft = await _draft(client)
            result = await _call(
                client,
                "change_undo",
                {"change": draft["change"]["id"], "reason": "not needed after all"},
            )

        assert not result.is_error, result
        undone = result.structured_content["undone"]
        assert undone["kind"] == "loop.delete"
        assert undone["undoes_id"] == draft["change"]["id"]
        assert undone["reason"] == "not needed after all"
        assert undone["who"]["user_id"] == "user-member"
        assert undone["via"]["client"]
        change = result.structured_content["change"]
        assert change["url"] == (
            f"{proxysvc.config.settings.console_origin}/changes?change={change['id']}"
        )

    async def test_a_repeated_undo_applies_once(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            draft = await _draft(client)
            arguments = {"change": draft["change"]["id"], "reason": "not needed"}
            first = await _call(client, "change_undo", arguments)
            second = await _call(client, "change_undo", arguments)

        assert not first.is_error and not second.is_error
        assert (
            first.structured_content["change"]["id"]
            == second.structured_content["change"]["id"]
        )

    async def test_a_launch_is_refused_with_what_to_do(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            launched = await _call(
                client, "loop_launch", {"loop": "checkout-headline", "reason": "go"}
            )
            result = await _call(
                client,
                "change_undo",
                {"change": launched.structured_content["change"]["id"], "reason": "no"},
            )

        assert _error(result).startswith(
            "Launching a loop starts its first cycle, so it cannot be undone."
        )

    async def test_a_moved_change_names_the_later_one(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            draft = await _draft(client)
            launched = await _call(
                client, "loop_launch", {"loop": "checkout-headline", "reason": "go"}
            )
            result = await _call(
                client,
                "change_undo",
                {"change": draft["change"]["id"], "reason": "no"},
            )

        message = _error(result)
        assert launched.structured_content["change"]["id"] in message
        assert message.endswith("Nothing was undone.")

    async def test_an_unknown_change_says_where_to_look(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            result = await _call(
                client, "change_undo", {"change": "nope", "reason": "no"}
            )

        assert _error(result) == (
            "No change with id nope. Call changes_list to see this workspace's changes."
        )

    async def test_a_viewer_reads_changes_and_cannot_undo(self, mcp, wired_app):
        async with _session(mcp, wired_app) as member:
            draft = await _draft(member)
        async with _session(mcp, wired_app, user="user-viewer") as viewer:
            read = await _call(viewer, "changes_list")
            result = await _call(
                viewer,
                "change_undo",
                {"change": draft["change"]["id"], "reason": "no"},
            )

        assert not read.is_error
        assert _error(result) == (
            "Your role can't undo this change. Ask an admin of this workspace."
        )


async def _live(client: Client) -> None:
    await _draft(client)
    result = await _call(
        client, "loop_launch", {"loop": "checkout-headline", "reason": "go"}
    )
    assert not result.is_error, result


COMMIT = {"loop": "checkout-headline", "option": "urgency", "reason": "it sells"}
REOPEN = {"loop": "checkout-headline", "reason": "new season"}


class TestCommitAndReopen:

    async def test_commit_says_what_happened_and_links_the_change(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(client, "loop_commit", COMMIT)

        assert not result.is_error, result
        structured = result.structured_content
        assert structured["status"] == "applied"
        assert structured["change"]["kind"] == "loop.commit"
        assert structured["change"]["undoable"] is True
        assert structured["loop"]["state"] == "committed"
        assert structured["loop"]["committed"] == "urgency"
        text = result.content[0].text
        assert text.startswith("Committed checkout-headline to urgency")
        assert "can be undone" in text
        assert structured["change"]["url"] in text

    async def test_commit_is_recorded_via_the_client_with_its_reason(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            committed = await _call(client, "loop_commit", COMMIT)
            result = await _call(client, "changes_list", {"kind": ["loop.commit"]})

        entry = result.structured_content["changes"][0]
        assert entry["id"] == committed.structured_content["change"]["id"]
        assert entry["reason"] == "it sells"
        assert entry["via"]["client"] == "Claude Code"
        line = result.content[0].text
        assert "Claude Code committed Checkout headline." in line
        assert "committed + urgency" in line

    async def test_reopen_returns_to_live_in_the_same_cycle(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_commit", COMMIT)
            result = await _call(client, "loop_reopen", REOPEN)

        assert not result.is_error, result
        loop = result.structured_content["loop"]
        assert (loop["state"], loop["committed"]) == ("live", None)
        assert loop["cycle"]["number"] == 1
        assert result.structured_content["change"]["kind"] == "loop.reopen"
        assert result.content[0].text.startswith(
            "Reopened checkout-headline: cycle 1 is live again"
        )

    async def test_loops_list_and_loop_get_name_the_committed_option(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_commit", COMMIT)
            listed = await _call(client, "loops_list", {"state": ["committed"]})
            got = await _call(client, "loop_get", {"loop": "checkout-headline"})

        assert [loop["key"] for loop in listed.structured_content["loops"]] == [
            "checkout-headline"
        ]
        assert "committed to urgency" in listed.content[0].text
        assert "committed to urgency" in got.content[0].text

    async def test_committing_a_draft_says_to_launch_it(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(client, "loop_commit", COMMIT)

        assert _error(result) == (
            "The loop checkout-headline is draft; nothing was committed. "
            "Launch it with loop_launch first."
        )

    async def test_committing_a_committed_loop_says_to_reopen_it(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_commit", COMMIT)
            result = await _call(client, "loop_commit", {**COMMIT, "option": "control"})

        assert _error(result) == (
            "The loop checkout-headline is committed; nothing was committed. "
            "It serves urgency already; reopen it with loop_reopen first to "
            "commit to another option."
        )

    async def test_an_unknown_option_names_the_options(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(client, "loop_commit", {**COMMIT, "option": "nope"})

        assert _error(result) == (
            "'nope' is not one of the loop's options (control, urgency). "
            "Call again with one of them; nothing was committed."
        )

    async def test_reopening_a_live_loop_is_refused(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(client, "loop_reopen", REOPEN)

        assert _error(result) == (
            "The loop checkout-headline is live; only a committed loop can be "
            "reopened. Nothing was changed."
        )

    async def test_undo_of_a_commit_reopens(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            committed = await _call(client, "loop_commit", COMMIT)
            result = await _call(
                client,
                "change_undo",
                {
                    "change": committed.structured_content["change"]["id"],
                    "reason": "too early",
                },
            )

        assert not result.is_error, result
        assert result.structured_content["change"]["kind"] == "loop.reopen"
        loop = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert (loop["state"], loop["committed"]) == ("live", None)


RETIRE = {"loop": "checkout-headline", "reason": "built into the page"}


class TestRetire:

    async def test_retire_says_what_happened_and_that_it_cant_be_undone(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_commit", COMMIT)
            result = await _call(client, "loop_retire", RETIRE)

        assert not result.is_error, result
        structured = result.structured_content
        assert structured["status"] == "applied"
        assert structured["change"]["kind"] == "loop.retire"
        assert structured["change"]["undoable"] is False
        loop = structured["loop"]
        assert (loop["state"], loop["committed"]) == ("retired", None)
        text = result.content[0].text
        assert text.startswith(
            "Retired checkout-headline: apps that still call it get its fallback"
        )
        assert "can't be undone" in text
        assert structured["change"]["url"] in text

    async def test_is_recorded_via_the_client_with_its_reason(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_retire", RETIRE)
            result = await _call(client, "changes_list", {"kind": ["loop.retire"]})

        entry = result.structured_content["changes"][0]
        assert entry["reason"] == "built into the page"
        assert entry["via"]["client"] == "Claude Code"
        assert "Claude Code retired Checkout headline." in result.content[0].text

    async def test_a_retired_loop_stays_readable(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_retire", RETIRE)
            listed = await _call(client, "loops_list", {"state": ["retired"]})
            got = await _call(client, "loop_get", {"loop": "checkout-headline"})
            results = await _call(client, "loop_results", {"loop": "checkout-headline"})

        assert [loop["key"] for loop in listed.structured_content["loops"]] == [
            "checkout-headline"
        ]
        assert got.structured_content["state"] == "retired"
        assert got.structured_content["latest_change"]["kind"] == "loop.retire"
        assert not results.is_error, results

    async def test_retiring_a_draft_says_to_delete_it(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(client, "loop_retire", RETIRE)

        assert _error(result) == (
            "The loop checkout-headline is draft; nothing was retired. "
            "A draft was never served: delete it in the console instead."
        )

    async def test_retiring_twice_says_it_is_retired_already(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_retire", RETIRE)
            result = await _call(client, "loop_retire", {**RETIRE, "reason": "again"})

        assert _error(result) == (
            "The loop checkout-headline is retired; nothing was retired. "
            "It is retired already."
        )

    async def test_committing_a_retired_loop_says_to_create_a_new_one(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_retire", RETIRE)
            result = await _call(client, "loop_commit", COMMIT)

        assert _error(result) == (
            "The loop checkout-headline is retired; nothing was committed. "
            "Create a new loop with loop_create to serve the choice again."
        )

    async def test_undo_of_a_retire_is_refused_with_why(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            retired = await _call(client, "loop_retire", RETIRE)
            result = await _call(
                client,
                "change_undo",
                {
                    "change": retired.structured_content["change"]["id"],
                    "reason": "oops",
                },
            )

        assert _error(result).startswith(
            "Retiring a loop says the choice has left the product, so it can't be "
            "undone; create a new loop to serve it again."
        )
        loop = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert loop["state"] == "retired"


CYCLE = {
    "loop": "checkout-headline",
    "reason": "try social proof",
    "options": [
        {"key": "control", "name": "Control", "config": {"headline": "Buy now"}},
        {"key": "urgency", "name": "Urgency", "config": {"headline": "Only 3 left"}},
        {"key": "social", "name": "Social proof", "config": {"headline": "Loved"}},
    ],
}
RESET = {"loop": "checkout-headline", "reason": "the page changed"}


class TestCycles:

    async def test_start_says_what_happened_and_that_it_cant_be_undone(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(client, "cycle_start", CYCLE)

        assert not result.is_error, result
        structured = result.structured_content
        assert structured["status"] == "applied"
        assert structured["change"]["kind"] == "cycle.start"
        assert structured["change"]["undoable"] is False
        loop = structured["loop"]
        assert loop["cycle"]["number"] == 2
        assert [o["key"] for o in loop["options"]] == ["control", "urgency", "social"]
        text = result.content[0].text
        assert text.startswith(
            "Started cycle 2 of checkout-headline: it learns afresh, and the "
            "earlier cycle stays readable."
        )
        assert "can't be undone" in text
        assert structured["change"]["url"] in text

    async def test_reset_keeps_the_options_and_is_recorded_via_the_client(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(client, "cycle_reset", RESET)
            listed = await _call(client, "changes_list", {"kind": ["cycle.reset"]})

        assert not result.is_error, result
        loop = result.structured_content["loop"]
        assert loop["cycle"]["number"] == 2
        assert [o["key"] for o in loop["options"]] == ["control", "urgency"]
        assert result.content[0].text.startswith(
            "Reset checkout-headline: cycle 2 learns afresh with the same options "
            "and engine"
        )
        entry = listed.structured_content["changes"][0]
        assert entry["reason"] == "the page changed"
        assert "Claude Code reset Checkout headline." in listed.content[0].text

    async def test_the_earlier_cycle_stays_readable(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "cycle_start", CYCLE)
            results = await _call(
                client, "loop_results", {"loop": "checkout-headline", "cycle": 1}
            )

        assert not results.is_error, results
        assert results.structured_content["cycle"]["number"] == 1

    @pytest.mark.parametrize(
        "steps, fix",
        [
            (
                [],
                "The loop checkout-headline is draft; no cycle was started. "
                "Launch it with loop_launch first; its first cycle starts then.",
            ),
            (
                [("loop_commit", COMMIT)],
                "The loop checkout-headline is committed; no cycle was started. "
                "A new cycle explores again: reopen it with loop_reopen first.",
            ),
            (
                [
                    ("loop_commit", COMMIT),
                    ("loop_pause", {"loop": "checkout-headline", "reason": "bug"}),
                ],
                "The loop checkout-headline is paused; no cycle was started. "
                "It was committed before the pause: resume it with loop_resume, "
                "then reopen it with loop_reopen first.",
            ),
            (
                [("loop_retire", RETIRE)],
                "The loop checkout-headline is retired; no cycle was started. "
                "Create a new loop with loop_create to serve the choice again.",
            ),
        ],
    )
    async def test_a_loop_that_cant_start_a_cycle_says_what_to_do(
        self, mcp, wired_app, steps, fix
    ):
        async with _session(mcp, wired_app) as client:
            if steps:
                await _live(client)
            else:
                await _draft(client)
            for tool, arguments in steps:
                done = await _call(client, tool, arguments)
                assert not done.is_error, done
            start = await _call(client, "cycle_start", CYCLE)
            reset = await _call(client, "cycle_reset", RESET)

        assert _error(start) == fix
        assert _error(reset) == fix

    async def test_a_dropped_fallback_says_to_name_one(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(
                client, "cycle_start", {**CYCLE, "options": CYCLE["options"][1:]}
            )

        assert _error(result) == (
            "The fallback 'control' is not one of the new options; name one of them "
            "as the fallback (urgency, social). Fix it and call again."
        )

    async def test_undo_of_a_start_is_refused_with_why(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            started = await _call(client, "cycle_start", CYCLE)
            result = await _call(
                client,
                "change_undo",
                {
                    "change": started.structured_content["change"]["id"],
                    "reason": "oops",
                },
            )

        assert _error(result).startswith(
            "Starting a cycle begins fresh learning, so it can't be undone; the "
            "earlier cycle stays readable."
        )


PAUSE = {"loop": "checkout-headline", "reason": "checkout bug"}


class TestPauseAndResume:

    async def test_pause_says_what_users_get_and_links_the_change(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(client, "loop_pause", PAUSE)

        assert not result.is_error, result
        structured = result.structured_content
        assert structured["change"]["kind"] == "loop.pause"
        assert structured["change"]["undoable"] is True
        loop = structured["loop"]
        assert (loop["state"], loop["paused_from"]) == ("paused", "live")
        text = result.content[0].text
        assert text.startswith(
            "Paused checkout-headline: everyone gets its fallback from now on"
        )
        assert structured["change"]["url"] in text

    async def test_pause_is_recorded_via_the_client_without_evidence(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_pause", PAUSE)
            result = await _call(client, "changes_list", {"kind": ["loop.pause"]})

        entry = result.structured_content["changes"][0]
        assert entry["reason"] == "checkout bug"
        assert entry["via"]["client"] == "Claude Code"
        assert entry.get("evidence") is None

    async def test_a_committed_loop_resumes_to_its_option(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_commit", COMMIT)
            paused = await _call(client, "loop_pause", PAUSE)
            result = await _call(client, "loop_resume", {**PAUSE, "reason": "fixed"})

        assert paused.structured_content["loop"]["paused_from"] == "committed"
        assert not result.is_error, result
        loop = result.structured_content["loop"]
        assert (loop["state"], loop["committed"]) == ("committed", "urgency")
        assert result.structured_content["change"]["kind"] == "loop.resume"
        assert result.content[0].text.startswith(
            "Resumed checkout-headline: it is committed to urgency again."
        )

    async def test_resume_of_a_live_loop_is_refused(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(client, "loop_resume", PAUSE)

        assert _error(result) == (
            "The loop checkout-headline is live; only a paused loop can be "
            "resumed. Nothing was changed. It is serving already."
        )

    async def test_pausing_a_draft_says_it_serves_its_fallback(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(client, "loop_pause", PAUSE)

        assert _error(result) == (
            "The loop checkout-headline is draft; nothing was paused. "
            "A draft serves its fallback until it is launched with loop_launch."
        )

    async def test_pausing_twice_says_to_resume(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_pause", PAUSE)
            result = await _call(client, "loop_pause", {**PAUSE, "reason": "again"})

        assert _error(result) == (
            "The loop checkout-headline is paused; nothing was paused. "
            "It is paused already; resume it with loop_resume."
        )

    async def test_committing_a_paused_loop_says_to_resume_it(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_pause", PAUSE)
            result = await _call(client, "loop_commit", COMMIT)

        assert _error(result).endswith("Resume it with loop_resume first.")

    async def test_a_paused_loop_retires(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_pause", PAUSE)
            result = await _call(client, "loop_retire", RETIRE)

        assert not result.is_error, result
        assert result.structured_content["loop"]["state"] == "retired"

    async def test_undo_of_a_pause_resumes(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            paused = await _call(client, "loop_pause", PAUSE)
            result = await _call(
                client,
                "change_undo",
                {
                    "change": paused.structured_content["change"]["id"],
                    "reason": "false alarm",
                },
            )

        assert not result.is_error, result
        assert result.structured_content["change"]["kind"] == "loop.resume"
        loop = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert loop["state"] == "live"


NOTE = {"loop": "checkout-headline", "text": "checkout copy is frozen until the 20th"}


class TestNotesAndHistory:

    async def test_note_add_is_recorded_via_the_client_and_links_it(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(client, "note_add", NOTE)

        assert not result.is_error, result
        change = result.structured_content["change"]
        note = result.structured_content["note"]
        assert (change["kind"], change["undoable"]) == ("note.add", False)
        assert change["url"] == (
            f"{proxysvc.config.settings.console_origin}/loops/checkout-headline"
            f"/history?change={change['id']}"
        )
        assert note["note"] == NOTE["text"]
        assert note["who"]["user_id"] == "user-member"
        assert note["via"]["client"] == "Claude Code"
        assert result.content[0].text == (
            f"Added a note to checkout-headline. Change {change['id']}, a note "
            f"stays in history: {change['url']}"
        )

    async def test_loop_history_reads_notes_beside_changes(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            await _call(client, "note_add", NOTE)
            result = await _call(client, "loop_history", {"loop": "checkout-headline"})

        assert not result.is_error, result
        kinds = [e["kind"] for e in result.structured_content["changes"]]
        assert kinds == ["note.add", "loop.create"]
        note_line, create_line = result.content[0].text.splitlines()[:2]
        assert "Claude Code added a note to Checkout headline." in note_line
        assert f'note "{NOTE["text"]}"' in note_line
        assert "can be undone" not in note_line
        assert "Claude Code created Checkout headline." in create_line
        assert result.structured_content["url"] == (
            f"{proxysvc.config.settings.console_origin}/loops/checkout-headline/history"
        )

    async def test_loop_history_shows_only_notes_or_only_changes(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            await _call(client, "note_add", NOTE)
            notes = await _call(
                client, "loop_history", {"loop": "checkout-headline", "show": "notes"}
            )
            changes = await _call(
                client, "loop_history", {"loop": "checkout-headline", "show": "changes"}
            )

        assert [e["kind"] for e in notes.structured_content["changes"]] == ["note.add"]
        assert [e["kind"] for e in changes.structured_content["changes"]] == [
            "loop.create"
        ]

    async def test_loop_history_pages_with_a_cursor(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            await _call(client, "note_add", NOTE)
            first = await _call(
                client, "loop_history", {"loop": "checkout-headline", "limit": 1}
            )
            second = await _call(
                client,
                "loop_history",
                {
                    "loop": "checkout-headline",
                    "limit": 1,
                    "cursor": first.structured_content["next_cursor"],
                },
            )

        assert "More history: call again with cursor" in first.content[0].text
        assert [e["kind"] for e in second.structured_content["changes"]] == [
            "loop.create"
        ]
        assert second.structured_content["next_cursor"] is None

    async def test_loop_history_refuses_an_unknown_loop(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(client, "loop_history", {"loop": "checkout-hedline"})

        assert "Did you mean checkout-headline?" in _error(result)

    async def test_a_blank_note_is_refused_with_the_fix(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(client, "note_add", {**NOTE, "text": "   "})

        assert _error(result) == "A note needs some text. Fix it and call again."

    async def test_a_note_after_a_pause_keeps_who_paused_it(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_pause", PAUSE)
            await _call(client, "note_add", NOTE)
            result = await _call(client, "loop_get", {"loop": "checkout-headline"})

        assert "Paused by Mustafa via Claude Code at" in result.content[0].text
        assert ": checkout bug. Everyone gets the fallback" in result.content[0].text


class TestViewer:

    async def test_a_viewer_reads_every_read_tool(self, mcp, wired_app):
        async with _session(mcp, wired_app) as member:
            draft = await _draft(member)
        async with _session(mcp, wired_app, user="user-viewer") as viewer:
            results = [
                await _call(viewer, "loops_list"),
                await _call(viewer, "loop_get", {"loop": "checkout-headline"}),
                await _call(viewer, "loop_results", {"loop": "checkout-headline"}),
                await _call(viewer, "metrics_list"),
                await _call(viewer, "changes_list"),
                await _call(viewer, "change_get", {"change": draft["change"]["id"]}),
                await _call(viewer, "loop_history", {"loop": "checkout-headline"}),
            ]

        assert not any(result.is_error for result in results)

    @pytest.mark.parametrize(
        "tool, arguments, verb",
        [
            ("loop_create", LOOP, "create loops"),
            ("loop_rename", {"loop": "x", "name": "y", "reason": "go"}, "rename loops"),
            ("loop_launch", {"loop": "x", "reason": "go"}, "launch loops"),
            (
                "loop_commit",
                {"loop": "x", "option": "control", "reason": "go"},
                "commit loops",
            ),
            ("loop_reopen", {"loop": "x", "reason": "go"}, "reopen loops"),
            ("loop_retire", {"loop": "x", "reason": "go"}, "retire loops"),
            ("loop_pause", {"loop": "x", "reason": "go"}, "pause loops"),
            ("loop_resume", {"loop": "x", "reason": "go"}, "resume loops"),
            ("cycle_start", {**CYCLE, "loop": "x"}, "start cycles"),
            ("cycle_reset", {"loop": "x", "reason": "go"}, "reset cycles"),
            (
                "delivery_update",
                {"loop": "x", "reason": "go", "rollout": 50},
                "change delivery",
            ),
            (
                "context_update",
                {"loop": "x", "reason": "go", "context": None},
                "change a loop's context",
            ),
            ("metric_create", METRIC, "create metrics"),
            ("note_add", {"loop": "x", "text": "hello"}, "add notes"),
        ],
    )
    async def test_a_viewer_gets_the_role_error_from_every_change_tool(
        self, mcp, wired_app, tool, arguments, verb
    ):
        async with _session(mcp, wired_app, user="user-viewer") as viewer:
            result = await _call(viewer, tool, arguments)

        assert _error(result) == (
            f"Your role can't {verb}. Ask an admin of this workspace."
        )


class TestReads:

    async def test_loop_get_says_how_to_wire_the_loop(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(client, "loop_get", {"loop": "checkout-headline"})

        wire = result.structured_content["wire"]
        assert '"checkout-headline"' in wire["python"]
        assert "client.outcome(decision.request_id, 1)" in wire["python"]
        assert '"key": "control"' in wire["javascript"]
        assert "qbrix.outcome(decision.requestId, 1)" in wire["javascript"]
        assert "```python" in result.content[0].text

    async def test_concise_leaves_out_option_config(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            concise = await _call(client, "loop_get", {"loop": "checkout-headline"})
            full = await _call(
                client, "loop_get", {"loop": "checkout-headline", "detail": "full"}
            )
            listed = await _call(client, "loops_list", {"detail": "full"})

        assert concise.structured_content["options"][0]["config"] is None
        assert full.structured_content["options"][0]["config"] == {
            "headline": "Buy now"
        }
        assert listed.structured_content["loops"][0]["options"][1]["config"] == {
            "headline": "Only 3 left"
        }

    async def test_lists_page_with_a_cursor(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            await _call(client, "loop_create", {**LOOP, "name": "Checkout button"})
            first = await _call(client, "loops_list", {"limit": 1})
            second = await _call(
                client,
                "loops_list",
                {"limit": 1, "cursor": first.structured_content["next_cursor"]},
            )

        assert [loop["key"] for loop in first.structured_content["loops"]] == [
            "checkout-button"
        ]
        assert [loop["key"] for loop in second.structured_content["loops"]] == [
            "checkout-headline"
        ]
        assert second.structured_content["next_cursor"] is None

    async def test_metrics_list_names_the_loops_using_each(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(client, "metrics_list")

        [metric] = result.structured_content["metrics"]
        assert [loop["key"] for loop in metric["loops"]] == ["checkout-headline"]
        assert "used by checkout-headline" in result.content[0].text

    async def test_loop_results_of_a_live_loop(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            await _call(
                client, "loop_launch", {"loop": "checkout-headline", "reason": "go"}
            )
            result = await _call(client, "loop_results", {"loop": "checkout-headline"})

        assert not result.is_error
        assert result.structured_content["cycle"]["number"] == 1
        assert result.structured_content["share"]["series"] is None

    async def test_a_loop_paused_by_qbrix_says_why_and_when(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            await _call(
                client, "loop_launch", {"loop": "checkout-headline", "reason": "go"}
            )
            live = await _call(client, "loop_get", {"loop": "checkout-headline"})
            await wired_app.svc.loops.pause_loop(
                TENANT,
                "checkout-headline",
                actor=Actor.qbrix(),
                reason="decision errors",
                evidence=EVIDENCE,
            )
            paused = await _call(client, "loop_get", {"loop": "checkout-headline"})
            listed = await _call(client, "loops_list")

        assert "Paused by" not in live.content[0].text
        assert re.search(
            r"^Paused by qbrix at \d{4}-\d\d-\d\d \d\d:\d\d UTC: 23\.8% of 629 calls "
            r"failed over 10 minutes \(motor_unavailable 150\)\. Everyone gets the "
            r"fallback until a person resumes it\.$",
            paused.content[0].text,
            re.MULTILINE,
        )
        assert paused.structured_content["latest_change"]["evidence"] == EVIDENCE
        assert (
            "latest loop.pause by qbrix · decision errors 23.8% of 629 calls"
            in listed.content[0].text
        )
        (loop,) = listed.structured_content["loops"]
        assert loop["latest_change"]["evidence"] == EVIDENCE


class TestRefusals:

    async def test_an_unknown_loop_suggests_the_close_one(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(client, "loop_get", {"loop": "checkout-hedline"})

        assert _error(result) == (
            "No loop with key or id checkout-hedline. Did you mean checkout-headline?"
        )

    async def test_an_unknown_loop_with_nothing_close_says_where_to_look(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            result = await _call(
                client, "loop_launch", {"loop": "nope", "reason": "go"}
            )

        assert _error(result) == (
            "No loop with key or id nope. Call loops_list to see this workspace's loops."
        )

    async def test_an_unknown_metric_suggests_one(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _call(client, "metric_create", METRIC)
            result = await _call(client, "loop_create", {**LOOP, "metric": "purchse"})

        assert _error(result) == (
            "No metric named or with id purchse. Did you mean purchase?"
        )

    async def test_launching_a_live_loop(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            await _call(
                client, "loop_launch", {"loop": "checkout-headline", "reason": "go"}
            )
            result = await _call(
                client,
                "loop_launch",
                {"loop": "checkout-headline", "reason": "once more"},
            )

        assert _error(result) == (
            "The loop checkout-headline is live already; launching applies only to drafts."
        )

    async def test_a_taken_key(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(
                client,
                "loop_create",
                {**LOOP, "key": "checkout-headline", "reason": "a second one"},
            )

        assert _error(result).endswith(
            "Choose another key, or leave key out to generate one from the name."
        )

    async def test_a_taken_metric_name(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _call(client, "metric_create", METRIC)
            result = await _call(client, "metric_create", {**METRIC, "reason": "again"})

        assert _error(result) == (
            "A metric named 'purchase' already exists. Use it as it is "
            "(metrics_list shows it), or choose another name."
        )

    async def test_an_invalid_loop(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _call(client, "metric_create", METRIC)
            result = await _call(client, "loop_create", {**LOOP, "fallback": "nope"})

        assert _error(result).startswith("The fallback 'nope' is not one of")
        assert _error(result).endswith("Fix it and call again.")

    async def test_an_invalid_metric(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            result = await _call(
                client, "metric_create", {**METRIC, "name": "Not A Name"}
            )

        assert _error(result).startswith("A metric name is what code sends")
        assert _error(result).endswith("Fix it and call again.")

    async def test_a_bad_cursor(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            result = await _call(client, "loops_list", {"cursor": "garbage"})

        assert _error(result) == (
            "That cursor isn't one this tool gave out. "
            "Call again without cursor to start from the newest."
        )

    async def test_a_cycle_the_loop_never_had(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            await _call(
                client, "loop_launch", {"loop": "checkout-headline", "reason": "go"}
            )
            result = await _call(
                client, "loop_results", {"loop": "checkout-headline", "cycle": 4}
            )

        assert _error(result) == (
            "The loop checkout-headline has no cycle 4; its cycles are 1 to 1. "
            "Leave cycle out for the current one."
        )

    async def test_a_reason_is_required(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            result = await _call(
                client,
                "metric_create",
                {k: v for k, v in METRIC.items() if k != "reason"},
            )

        assert "reason" in _error(result)


class TestAutonomy:

    async def test_loop_get_returns_this_connections_levels(self, mcp, wired_app):
        async with _session(mcp, wired_app, levels=None) as client:
            await _draft(client)
            await wired_app.svc.connections.set_levels(
                TENANT,
                await _connection_id(wired_app),
                {"loop.launch": "notify"},
                actor=Actor.member("user-member"),
                role="member",
            )
            result = await _call(client, "loop_get", {"loop": "checkout-headline"})

        levels = result.structured_content["autonomy"]
        assert levels["loop.launch"] == "notify"
        assert levels["cycle.start"] == "ask"
        assert levels["note.add"] == "own"
        assert "loop.create" not in levels and "metric.create" not in levels
        assert (
            "Your autonomy here: ask first: cycle_start, loop_retire; "
            "act and notify: loop_launch," in result.content[0].text
        )

    async def test_a_connection_cant_undo_its_levels(self, mcp, wired_app):
        async with _session(mcp, wired_app, levels=None) as client:
            changed = await wired_app.svc.connections.set_levels(
                TENANT,
                await _connection_id(wired_app),
                {"loop.launch": "notify"},
                actor=Actor.member("user-member"),
                role="member",
            )
            result = await _call(
                client,
                "change_undo",
                {"change": changed["change_id"], "reason": "raise it back"},
            )

        assert _error(result) == (
            "A connection's levels are set by its person in the console, never "
            "over MCP. Nothing was undone."
        )


async def _connection_id(wired_app, user: str = "user-member") -> str:
    [connection] = await wired_app.svc.connections.list(
        TENANT, user_id=user, role=PEOPLE[user][0]
    )
    return connection["id"]


async def _approve(wired_app, change_id: str, **kwargs) -> dict:
    return await wired_app.svc.approve_change(
        TENANT,
        change_id,
        actor=Actor.member("user-member"),
        role="member",
        where="qbrix",
        **kwargs,
    )


async def _decline(wired_app, change_id: str, reason: str) -> dict:
    return await wired_app.svc.decline_change(
        TENANT,
        change_id,
        actor=Actor.member("user-member"),
        where="qbrix",
        reason=reason,
    )


LAUNCH = {"loop": "checkout-headline", "reason": "the select call is in"}


class TestAskingFirst:

    async def test_a_launch_waits_and_a_create_applies(self, mcp, wired_app):
        async with _session(mcp, wired_app, levels=None) as client:
            draft = await _draft(client)
            launched = await _call(client, "loop_launch", LAUNCH)

        assert draft["status"] == "applied"
        assert not launched.is_error, launched
        structured = launched.structured_content
        assert structured["status"] == "waiting"
        assert structured["loop"]["state"] == "draft"
        assert structured["change"]["kind"] == "loop.launch"
        assert structured["change"]["url"] == (
            f"{proxysvc.config.settings.console_origin}/changes"
            f"?change={structured['change']['id']}"
        )
        text = launched.content[0].text
        assert text.startswith(
            "Waiting for approval: Claude Code asks to launch Checkout headline."
        )
        assert "Nothing has changed yet. Mustafa approves or declines it" in text
        loop = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert loop["state"] == "draft"

    async def test_a_second_launch_names_the_one_waiting(self, mcp, wired_app):
        async with _session(mcp, wired_app, levels=None) as client:
            await _draft(client)
            first = await _call(client, "loop_launch", LAUNCH)
            again = await _call(
                client, "loop_launch", {**LAUNCH, "reason": "really ready now"}
            )

        waiting = first.structured_content["change"]["id"]
        assert f"({waiting})" in _error(again)
        assert "find its answer with change_get" in _error(again)

    async def test_an_approved_launch_reads_who_approved_where(self, mcp, wired_app):
        async with _session(mcp, wired_app, levels=None) as client:
            await _draft(client)
            launched = await _call(client, "loop_launch", LAUNCH)
            await _approve(wired_app, launched.structured_content["change"]["id"])
            history = await _call(client, "loop_history", {"loop": "checkout-headline"})

        newest = history.structured_content["changes"][0]
        assert newest["status"] == "applied"
        assert newest["decision"]["where"] == "qbrix"
        assert "approved by Mustafa in qbrix" in history.content[0].text.splitlines()[0]
        loop = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert loop["state"] == "live"

    async def test_a_decline_reaches_the_agent_with_its_reason(self, mcp, wired_app):
        reason = "not before legal approves the copy on 1 March"
        async with _session(mcp, wired_app, levels=None) as client:
            await _draft(client)
            launched = await _call(client, "loop_launch", LAUNCH)
            await _decline(
                wired_app, launched.structured_content["change"]["id"], reason
            )
            got = await _call(client, "loop_get", {"loop": "checkout-headline"})
            history = await _call(client, "loop_history", {"loop": "checkout-headline"})
            listed = await _call(client, "changes_list", {"kind": ["loop.launch"]})

        [declined] = got.structured_content["declined"]
        assert declined["decision"]["reason"] == reason
        assert "Declined recently, read before proposing again:" in got.content[0].text
        assert f'declined by Mustafa in qbrix: "{reason}"' in history.content[0].text
        assert listed.structured_content["changes"][0]["status"] == "declined"

    async def test_changes_list_holds_waiting_changes(self, mcp, wired_app):
        async with _session(mcp, wired_app, levels=None) as client:
            await _draft(client)
            await _call(client, "loop_launch", LAUNCH)
            listed = await _call(client, "changes_list", {"kind": ["loop.launch"]})

        [entry] = listed.structured_content["changes"]
        assert entry["status"] == "waiting"
        assert "waiting for approval" in listed.content[0].text

    async def test_an_undo_asks_at_the_level_of_what_it_undoes(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            paused = await _call(
                client, "loop_pause", {"loop": "checkout-headline", "reason": "check"}
            )
            await wired_app.svc.connections.set_levels(
                TENANT,
                await _connection_id(wired_app),
                {"loop.pause": "ask"},
                actor=Actor.member("user-member"),
                role="member",
            )
            undo = await _call(
                client,
                "change_undo",
                {
                    "change": paused.structured_content["change"]["id"],
                    "reason": "it was fine",
                },
            )

        assert not undo.is_error, undo
        assert undo.structured_content["status"] == "waiting"
        assert undo.structured_content["undone"]["kind"] == "loop.resume"
        loop = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert loop["state"] == "paused"

    async def test_approving_can_raise_the_level_as_its_own_change(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app, levels=None) as client:
            await _draft(client)
            launched = await _call(client, "loop_launch", LAUNCH)
            await _approve(
                wired_app,
                launched.structured_content["change"]["id"],
                raise_level=True,
            )
            got = await _call(client, "loop_get", {"loop": "checkout-headline"})
            levels = await _call(
                client, "changes_list", {"kind": ["connection.levels"]}
            )

        assert got.structured_content["autonomy"]["loop.launch"] == "notify"
        [raised] = levels.structured_content["changes"]
        assert raised["who"]["user_id"] == "user-member"
        assert raised["via"] is None


APPROVE = {"answer": "approve"}


def _answering(action: str = "accept", content: dict | None = None, asked=None):
    """a person who answers every question the same way, noting what was asked."""

    async def answer(context, params):
        if asked is not None:
            asked.append(params)
        return ElicitResult(action=action, content=content)

    return answer


async def _asked(client: Client, tool: str, arguments: dict) -> InputRequiredResult:
    """the question as the wire carries it, for a test to answer by hand."""
    result = await client.session.call_tool(tool, arguments, allow_input_required=True)
    assert isinstance(result, InputRequiredResult), result
    return result


def _reply(content: dict | None = None, action: str = "accept") -> dict:
    return {"answer": ElicitResult(action=action, content=content)}


class TestAskingInChat:

    async def test_approving_in_the_chat_launches_and_says_where(self, mcp, wired_app):
        asked = []
        async with _session(
            mcp, wired_app, levels=None, answer=_answering(content=APPROVE, asked=asked)
        ) as client:
            await _draft(client)
            launched = await _call(client, "loop_launch", LAUNCH)
            again = await _call(client, "loop_launch", LAUNCH)
            history = await _call(client, "loop_history", {"loop": "checkout-headline"})

        [question] = asked
        assert question.message == (
            "Claude Code asks to launch Checkout headline. "
            'Reason: "the select call is in". Nothing applies until you answer.'
        )
        assert question.requested_schema["properties"]["answer"]["default"] == "approve"
        assert not launched.is_error, launched
        structured = launched.structured_content
        assert structured["status"] == "applied"
        assert structured["loop"]["state"] == "live"
        assert structured["change"]["url"].endswith(
            f"/loops/checkout-headline/history?change={structured['change']['id']}"
        )
        assert launched.content[0].text.startswith(
            "Approved by Mustafa in Claude Code: "
        )
        assert _error(again).startswith("The loop checkout-headline is live already")
        newest = history.structured_content["changes"][0]
        assert newest["decision"]["answer"] == "approved"
        assert newest["decision"]["where"] == "Claude Code"
        assert "approved by Mustafa in Claude Code" in history.content[0].text

    async def test_declining_with_a_reason_keeps_it(self, mcp, wired_app):
        answer = _answering(content={"answer": "decline", "reason": "  legal first "})
        async with _session(mcp, wired_app, levels=None, answer=answer) as client:
            await _draft(client)
            launched = await _call(client, "loop_launch", LAUNCH)

        structured = launched.structured_content
        assert structured["status"] == "declined"
        assert structured["loop"]["state"] == "draft"
        assert launched.content[0].text.startswith(
            'Declined by Mustafa in Claude Code: "legal first". Nothing changed'
        )
        entry = await wired_app.svc.get_change_entry(TENANT, structured["change"]["id"])
        assert entry["status"] == "declined"
        assert entry["decision"]["reason"] == "legal first"
        assert entry["decision"]["where"] == "Claude Code"

    async def test_the_clients_own_decline_declines_without_a_reason(
        self, mcp, wired_app
    ):
        async with _session(
            mcp, wired_app, levels=None, answer=_answering(action="decline")
        ) as client:
            await _draft(client)
            launched = await _call(client, "loop_launch", LAUNCH)

        assert launched.structured_content["status"] == "declined"
        entry = await wired_app.svc.get_change_entry(
            TENANT, launched.structured_content["change"]["id"]
        )
        assert entry["decision"]["reason"] is None

    async def test_closing_the_question_leaves_it_waiting(self, mcp, wired_app):
        async with _session(
            mcp, wired_app, levels=None, answer=_answering(action="cancel")
        ) as client:
            await _draft(client)
            launched = await _call(client, "loop_launch", LAUNCH)

        structured = launched.structured_content
        assert structured["status"] == "waiting"
        assert launched.content[0].text.startswith("Waiting for approval:")
        approved = await _approve(wired_app, structured["change"]["id"])
        assert approved["status"] == "applied"

    @pytest.mark.parametrize("mode, can_ask", [(MODERN, False), (LEGACY, True)])
    async def test_a_client_that_cant_ask_gets_the_console_link(
        self, mcp, wired_app, mode, can_ask
    ):
        asked = []
        answer = _answering(content=APPROVE, asked=asked) if can_ask else None
        async with _session(
            mcp, wired_app, mode=mode, levels=None, answer=answer
        ) as client:
            await _draft(client)
            launched = await _call(client, "loop_launch", LAUNCH)

        assert asked == []
        assert launched.structured_content["status"] == "waiting"
        assert "/changes?change=" in launched.content[0].text

    async def test_an_answer_is_taken_once(self, mcp, wired_app):
        async with _session(
            mcp, wired_app, levels=None, answer=_answering(content=APPROVE)
        ) as client:
            await _draft(client)
            question = await _asked(client, "loop_launch", LAUNCH)
            first = await client.call_tool(
                "loop_launch",
                LAUNCH,
                input_responses=_reply(APPROVE),
                request_state=question.request_state,
            )
            replayed = await client.call_tool(
                "loop_launch",
                LAUNCH,
                input_responses=_reply({"answer": "decline"}),
                request_state=question.request_state,
            )

        assert first.structured_content["status"] == "applied"
        assert _error(replayed).startswith(
            f"Change {first.structured_content['change']['id']} was already "
            f"approved by Mustafa in Claude Code"
        )

    async def test_an_edited_question_is_refused(self, mcp, wired_app):
        async with _session(
            mcp, wired_app, levels=None, answer=_answering(content=APPROVE)
        ) as client:
            await _draft(client)
            question = await _asked(client, "loop_launch", LAUNCH)
            state = question.request_state
            edited = state[:-6] + (
                "AAAAAA" if not state.endswith("AAAAAA") else "BBBBBB"
            )
            with pytest.raises(Exception, match="requestState"):
                await client.call_tool(
                    "loop_launch",
                    LAUNCH,
                    input_responses=_reply(APPROVE),
                    request_state=edited,
                )
            with pytest.raises(Exception, match="requestState"):
                await client.call_tool(
                    "loop_launch",
                    {**LAUNCH, "reason": "something else"},
                    input_responses=_reply(APPROVE),
                    request_state=state,
                )

        loop = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert loop["state"] == "draft"

    async def test_another_connection_cant_answer(self, mcp, wired_app):
        async with _session(
            mcp, wired_app, levels=None, answer=_answering(content=APPROVE)
        ) as client:
            await _draft(client)
            question = await _asked(client, "loop_launch", LAUNCH)
        cursor = await _token(wired_app, client="Cursor")
        async with _connect(_http(mcp, cursor)) as other:
            with pytest.raises(Exception, match="requestState"):
                await other.call_tool(
                    "loop_launch",
                    LAUNCH,
                    input_responses=_reply(APPROVE),
                    request_state=question.request_state,
                )

        loop = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert loop["state"] == "draft"

    async def test_any_replica_takes_the_answer(self, mcp, wired_app):
        replicas = []
        for _ in range(2):
            server, asgi = build_mcp(proxysvc.config.settings)
            replicas.append((server, Starlette(routes=[Route(MCP_PATH, asgi)])))
        transport = _RoundRobin(
            [httpx2.ASGITransport(app=replica) for _, replica in replicas]
        )
        token = await _token(wired_app)
        await wired_app.svc.connections.set_levels(
            TENANT,
            await _connection_id(wired_app),
            {"loop.create": "ask"},
            actor=Actor.member("user-member"),
            role="member",
        )
        http = httpx2.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        )

        async with replicas[0][0].session_manager.run():
            async with replicas[1][0].session_manager.run():
                async with _connect(http, answer=_answering(content=APPROVE)) as client:
                    await _call(client, "metric_create", METRIC)
                    question = await _asked(client, "loop_create", LOOP)
                    created = await client.call_tool(
                        "loop_create",
                        LOOP,
                        input_responses=_reply(APPROVE),
                        request_state=question.request_state,
                    )

        assert transport.served == {0, 1}
        assert created.structured_content["status"] == "applied", created
        assert created.structured_content["loop"]["key"] == "checkout-headline"

    async def test_the_answer_counts_as_the_change_it_answers(
        self, mcp, wired_app, monkeypatch
    ):
        monkeypatch.setattr(wired_app.svc._settings, "mcp_changes_per_minute", 3)
        async with _session(
            mcp, wired_app, levels=None, answer=_answering(content=APPROVE)
        ) as client:
            await _draft(client)
            launched = await _call(client, "loop_launch", LAUNCH)

        assert launched.structured_content["status"] == "applied", launched

    async def test_a_metric_asked_in_the_chat_reads_as_created(self, mcp, wired_app):
        token = await _token(wired_app)
        await wired_app.svc.connections.set_levels(
            TENANT,
            await _connection_id(wired_app),
            {"metric.create": "ask"},
            actor=Actor.member("user-member"),
            role="member",
        )
        async with _connect(
            _http(mcp, token), answer=_answering(content=APPROVE)
        ) as client:
            created = await _call(client, "metric_create", METRIC)

        structured = created.structured_content
        assert structured["status"] == "applied", created
        assert structured["metric"]["name"] == "purchase"
        assert structured["change"]["url"].endswith(
            f"/metrics/purchase?change={structured['change']['id']}"
        )


RENAME = {
    "loop": "checkout-headline",
    "name": "Checkout title",
    "reason": "support calls it the title",
}


class TestChangeGetAndRename:

    async def test_change_get_reads_a_persons_console_change(self, mcp, wired_app):
        async with _session(mcp, wired_app) as member:
            await _draft(member)
        renamed = await wired_app.svc.act(
            TENANT,
            "loop.rename",
            "checkout-headline",
            {"name": "Checkout title"},
            actor=Actor.member("user-member"),
            reason="support calls it the title",
        )
        change_id = renamed.change["id"]
        async with _session(mcp, wired_app, user="user-viewer") as viewer:
            result = await _call(viewer, "change_get", {"change": change_id})

        assert not result.is_error, result
        entry = result.structured_content
        assert entry["id"] == change_id
        assert entry["status"] == "applied"
        assert entry["who"]["user_id"] == "user-member"
        assert entry["via"] is None
        assert entry["reason"] == "support calls it the title"
        assert entry["url"] == (
            f"{proxysvc.config.settings.console_origin}/changes?change={change_id}"
        )
        text = result.content[0].text
        assert "Mustafa renamed" in text
        assert "name Checkout headline -> Checkout title" in text
        assert '"support calls it the title"' in text
        assert "can be undone" in text
        assert text.endswith(f"In the console: {entry['url']}")

    async def test_change_get_follows_a_waiting_change_to_its_answer(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app, levels=None) as client:
            await _draft(client)
            launched = await _call(client, "loop_launch", LAUNCH)
            change_id = launched.structured_content["change"]["id"]
            waiting = await _call(client, "change_get", {"change": change_id})
            await _approve(wired_app, change_id)
            approved = await _call(client, "change_get", {"change": change_id})

        assert waiting.structured_content["status"] == "waiting"
        assert "waiting for approval" in waiting.content[0].text
        assert approved.structured_content["status"] == "applied"
        assert approved.structured_content["decision"]["answer"] == "approved"
        assert "approved by Mustafa in qbrix" in approved.content[0].text

    async def test_another_workspaces_change_is_unknown(self, mcp, wired_app):
        async with session_module.get_session() as session:
            session.add(Tenant(id="tenant-b", name="tenant-b", slug="tenant-b"))
            session.add(
                User(
                    id="user-b",
                    tenant_id="tenant-b",
                    email="user-b@example.com",
                    password_hash="x",
                    name="Bo",
                    role="member",
                )
            )
        created = await wired_app.svc.act(
            "tenant-b",
            "metric.create",
            None,
            {
                "name": "purchase",
                "semantic": "a completed checkout",
                "metric_type": "conversion",
                "score_range": None,
                "window_seconds": 86400,
            },
            actor=Actor.member("user-b"),
        )
        change_id = created.change["id"]
        async with _session(mcp, wired_app) as client:
            result = await _call(client, "change_get", {"change": change_id})

        assert _error(result) == (
            f"No change with id {change_id}. "
            f"Call changes_list to see this workspace's changes."
        )

    async def test_loop_rename_is_recorded_via_the_client_and_undoes(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            renamed = await _call(client, "loop_rename", RENAME)
            change_id = renamed.structured_content["change"]["id"]
            got = await _call(client, "change_get", {"change": change_id})
            undo = await _call(
                client,
                "change_undo",
                {"change": change_id, "reason": "support changed its mind"},
            )

        assert not renamed.is_error, renamed
        structured = renamed.structured_content
        assert structured["status"] == "applied"
        assert structured["change"]["kind"] == "loop.rename"
        assert structured["change"]["undoable"] is True
        assert structured["loop"]["name"] == "Checkout title"
        assert structured["loop"]["key"] == "checkout-headline"
        assert renamed.content[0].text.startswith(
            "Renamed checkout-headline to Checkout title; its key stays"
        )
        entry = got.structured_content
        assert entry["who"]["user_id"] == "user-member"
        assert entry["via"]["client"] == "Claude Code"
        assert entry["reason"] == RENAME["reason"]
        assert "Mustafa via Claude Code" in got.content[0].text
        assert not undo.is_error, undo
        loop = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert loop["name"] == "Checkout headline"

    async def test_renaming_an_unknown_loop_suggests_the_close_one(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(
                client, "loop_rename", {**RENAME, "loop": "checkout-hedline"}
            )

        assert "Did you mean checkout-headline?" in _error(result)

    async def test_a_blank_name_is_refused_with_the_fix(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _draft(client)
            result = await _call(client, "loop_rename", {**RENAME, "name": "  "})

        assert _error(result).endswith("Fix it and call again.")


FORBIDDEN = (
    "winner",
    "significant",
    "ready to commit",
    "arm",
    "bandit",
    "policy",
    "reward",
    "regret",
    "explore",
    "exploit",
    "experiment",
)


class TestWorkspaceSummary:

    async def test_reads_the_same_as_the_service(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(client, "workspace_summary")

        week = await wired_app.svc.workspace_summary(TENANT)
        assert [loop["id"] for loop in result.structured_content["loops"]] == [
            loop["id"] for loop in week["loops"]
        ]
        assert result.structured_content["changes"]["total"] == (
            week["changes"]["total"]
        )

    async def test_says_the_week_in_product_words(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(client, "loop_create", {**LOOP, "name": "Search ranking"})
            await _call(
                client, "loop_launch", {"loop": "search-ranking", "reason": "go"}
            )
            await wired_app.svc.loops.pause_loop(
                TENANT,
                "search-ranking",
                actor=Actor.qbrix(),
                reason="decision errors",
                evidence=EVIDENCE,
            )
            result = await _call(client, "workspace_summary")

        text = result.content[0].text
        lines = text.splitlines()
        assert lines[0].startswith("Since ")
        assert "1 live, 1 paused, 0 committed loops" in lines[0]
        assert lines[1].startswith("Search ranking (search-ranking) · paused")
        assert "qbrix paused it" in text
        assert "23.8% of 629 calls failed; still paused" in text
        assert "Mustafa via Claude Code (" in text
        assert "Checkout headline (checkout-headline) · live" in text
        for word in FORBIDDEN:
            assert word not in text.lower(), word

    async def test_refuses_since_further_back_than_thirty_days(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            result = await _call(
                client, "workspace_summary", {"since": "2020-01-01T00:00:00Z"}
            )

        assert result.is_error
        assert "30 days" in _error(result)
        assert "on or after" in _error(result)


MOBILE_NL = [
    {"property": "device", "operator": "is", "value": "mobile"},
    {"property": "country", "operator": "in", "value": ["NL", "BE"]},
]
DELIVERY = {
    "loop": "checkout-headline",
    "reason": "only mobile visitors in NL and BE see it",
    "audience": MOBILE_NL,
    "rollout": 50,
}


class TestDelivery:

    async def test_a_new_loop_reads_as_deciding_for_everyone(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            got = await _call(client, "loop_get", {"loop": "checkout-headline"})

        text = got.content[0].text
        assert "Decides for: everyone, always. Everyone else gets control." in text
        assert got.structured_content["delivery"]["rollout"] == 100

    async def test_update_says_who_it_decides_for_and_can_be_undone(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(client, "delivery_update", DELIVERY)
            got = await _call(client, "loop_get", {"loop": "checkout-headline"})

        assert not result.is_error, result
        structured = result.structured_content
        assert structured["status"] == "applied"
        assert structured["change"]["kind"] == "delivery.update"
        assert structured["change"]["undoable"] is True
        assert structured["loop"]["delivery"]["audience"] == MOBILE_NL
        line = (
            "Decides for: device is mobile and country in NL, BE · 50% of them. "
            "Everyone else gets control."
        )
        assert line in result.content[0].text
        assert "can be undone" in result.content[0].text
        assert line in got.content[0].text

    async def test_outside_its_hours_it_says_everyone_gets_the_fallback(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(
                client,
                "delivery_update",
                {
                    "loop": "checkout-headline",
                    "reason": "launch in the new year",
                    "schedule": {"starts_on": "2999-01-01", "timezone": "UTC"},
                },
            )

        assert not result.is_error, result
        assert (
            "Right now everyone gets control: it starts on 2999-01-01."
            in result.content[0].text
        )

    async def test_a_change_that_cant_apply_says_why(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(
                client,
                "delivery_update",
                {
                    "loop": "checkout-headline",
                    "reason": "office hours",
                    "schedule": {"hours": {"start": "09:00", "end": "18:00"}},
                },
            )

        assert "needs its timezone" in _error(result)
        assert "Fix it and call again." in _error(result)

    async def test_a_retired_loop_is_refused_with_what_to_do(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(
                client, "loop_retire", {"loop": "checkout-headline", "reason": "gone"}
            )
            result = await _call(client, "delivery_update", DELIVERY)

        assert _error(result).startswith(
            "The loop checkout-headline is retired; nothing was changed."
        )

    async def test_acting_and_notifying_is_the_default(self, mcp, wired_app):
        async with _session(mcp, wired_app, levels=None) as client:
            await _live_by_approval(client, wired_app)
            result = await _call(client, "delivery_update", DELIVERY)

        assert result.structured_content["status"] == "applied"

    async def test_at_ask_it_waits_and_applies_when_approved(self, mcp, wired_app):
        async with _session(
            mcp, wired_app, levels={**ON_ITS_OWN, "delivery.update": "ask"}
        ) as client:
            await _live(client)
            asked = await _call(client, "delivery_update", DELIVERY)

        assert asked.structured_content["status"] == "waiting"
        assert asked.content[0].text.startswith(
            "Waiting for approval: Claude Code asks to change the delivery of "
            "Checkout headline."
        )
        waiting = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert waiting["delivery"]["rollout"] == 100

        await _approve(wired_app, asked.structured_content["change"]["id"])

        applied = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert applied["delivery"]["audience"] == MOBILE_NL
        assert applied["delivery"]["rollout"] == 50


async def _live_by_approval(client: Client, wired_app) -> None:
    await _draft(client)
    asked = await _call(client, "loop_launch", LAUNCH)
    await _approve(wired_app, asked.structured_content["change"]["id"])


PLAN = {"name": "plan", "type": "categorical", "values": ["free", "pro"]}
CONTEXT = {
    "loop": "checkout-headline",
    "reason": "pro accounts may want something else",
    "context": [PLAN],
}


async def _on_leibniz(client: Client) -> None:
    await _draft(client)
    declared = await _call(client, "context_update", CONTEXT)
    assert not declared.is_error, declared
    launched = await _call(
        client, "loop_launch", {"loop": "checkout-headline", "reason": "go"}
    )
    assert not launched.is_error, launched
    started = await _call(
        client,
        "cycle_start",
        {"loop": "checkout-headline", "reason": "personalise", "engine": "leibniz"},
    )
    assert not started.is_error, started


class TestContext:
    async def test_on_spinoza_it_applies_says_what_arrives_and_can_be_undone(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(client, "context_update", CONTEXT)
            got = await _call(client, "loop_get", {"loop": "checkout-headline"})

        assert not result.is_error, result
        structured = result.structured_content
        assert structured["status"] == "applied"
        assert structured["change"]["kind"] == "context.update"
        assert structured["change"]["undoable"] is True
        assert structured["loop"]["context"] == [PLAN]
        text = result.content[0].text
        assert text.startswith(
            "Changed the context of checkout-headline. Learns from: plan."
        )
        assert "Of 0 decisions in the last day: plan not arriving yet." in text
        assert "can be undone" in text
        assert "Learns from: plan." in got.content[0].text
        assert got.structured_content["context"] == [PLAN]

    async def test_on_leibniz_it_starts_a_cycle_that_cant_be_undone(
        self, mcp, wired_app
    ):
        async with _session(mcp, wired_app) as client:
            await _on_leibniz(client)
            result = await _call(
                client,
                "context_update",
                {
                    **CONTEXT,
                    "context": [PLAN, {"name": "returning", "type": "boolean"}],
                },
            )

        assert not result.is_error, result
        assert result.structured_content["change"]["undoable"] is False
        assert "Started cycle 3, which learns afresh." in result.content[0].text
        assert "can't be undone" in result.content[0].text

    async def test_on_leibniz_it_asks_first_when_starting_a_cycle_does(
        self, mcp, wired_app
    ):
        levels = {**ON_ITS_OWN, "context.update": "own"}
        async with _session(mcp, wired_app, levels=levels) as client:
            await _on_leibniz(client)
        async with _session(
            mcp, wired_app, levels={**levels, "cycle.start": "ask"}
        ) as client:
            asked = await _call(
                client,
                "context_update",
                {**CONTEXT, "context": [{"name": "returning", "type": "boolean"}]},
            )

        assert asked.structured_content["status"] == "waiting"
        assert asked.content[0].text.startswith(
            "Waiting for approval: Claude Code asks to change the context of "
            "Checkout headline."
        )
        waiting = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert waiting["context"] == [PLAN]

        await _approve(wired_app, asked.structured_content["change"]["id"])

        applied = await wired_app.svc.get_loop(TENANT, "checkout-headline")
        assert applied["context"] == [{"name": "returning", "type": "boolean"}]
        assert applied["cycle"]["number"] == 3

    async def test_acting_and_notifying_is_the_default_on_spinoza(self, mcp, wired_app):
        async with _session(mcp, wired_app, levels=None) as client:
            await _live_by_approval(client, wired_app)
            result = await _call(client, "context_update", CONTEXT)

        assert result.structured_content["status"] == "applied"

    async def test_a_committed_leibniz_loop_says_to_reopen_it(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _on_leibniz(client)
            await _call(client, "loop_commit", COMMIT)
            result = await _call(
                client,
                "context_update",
                {**CONTEXT, "context": [{"name": "returning", "type": "boolean"}]},
            )

        assert "reopen it with loop_reopen first" in _error(result)

    async def test_a_retired_loop_is_refused_with_what_to_do(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            await _call(
                client, "loop_retire", {"loop": "checkout-headline", "reason": "gone"}
            )
            result = await _call(client, "context_update", CONTEXT)

        assert _error(result).startswith(
            "The loop checkout-headline is retired; nothing was changed."
        )

    async def test_an_invalid_context_says_why(self, mcp, wired_app):
        async with _session(mcp, wired_app) as client:
            await _live(client)
            result = await _call(
                client,
                "context_update",
                {
                    **CONTEXT,
                    "context": [{"name": "plan", "type": "categorical", "values": []}],
                },
            )

        assert "context.0.values" in _error(result).lower()

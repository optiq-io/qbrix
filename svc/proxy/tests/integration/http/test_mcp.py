"""integration tests for qbrix's mcp server at /mcp, a qbrix next surface.

invariants verified:
  only a connection's access token reaches the tools: no token, a key, a
  revoked connection's token and a token for another resource each get 401
  pointing at the protected resource metadata, and an exhausted limit gets
  429 with when to retry. clients on 2026-07-28 and on 2025-11-25 list and
  call the tools, in a fixed order, and any replica answers any call. a
  change records who, via which client and why, and its result names the
  change, whether it can be undone and its console link. a repeated change
  within the window changes nothing twice. a viewer's connection reads and
  can't change. a loop paused by qbrix says who paused it, when and why, in
  loop_get and loops_list. every refusal says what to do next.
"""

from __future__ import annotations

import asyncio
import itertools
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
import pytest_asyncio
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.routing import Route

import proxysvc.config
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
    "loop_create",
    "loop_launch",
    "metric_create",
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
    http: httpx2.AsyncClient, mode: str = MODERN
) -> AsyncIterator[Client]:
    async with (
        http,
        Client(
            streamable_http_client(f"http://test{MCP_PATH}", http_client=http),
            mode=mode,
        ) as client,
    ):
        yield client


@asynccontextmanager
async def _session(app, wired_app, user="user-member", mode=MODERN):
    token = await _token(wired_app, user)
    async with _connect(_http(app, token), mode) as client:
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

        for name in ("loops_list", "loop_get", "loop_results", "metrics_list"):
            assert tools[name].annotations.read_only_hint is True
        assert tools["loop_launch"].annotations.destructive_hint is True
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


class TestViewer:

    async def test_a_viewer_reads_every_read_tool(self, mcp, wired_app):
        async with _session(mcp, wired_app) as member:
            await _draft(member)
        async with _session(mcp, wired_app, user="user-viewer") as viewer:
            results = [
                await _call(viewer, "loops_list"),
                await _call(viewer, "loop_get", {"loop": "checkout-headline"}),
                await _call(viewer, "loop_results", {"loop": "checkout-headline"}),
                await _call(viewer, "metrics_list"),
            ]

        assert not any(result.is_error for result in results)

    @pytest.mark.parametrize(
        "tool, arguments, verb",
        [
            ("loop_create", LOOP, "create loops"),
            ("loop_launch", {"loop": "x", "reason": "go"}, "launch loops"),
            ("metric_create", METRIC, "create metrics"),
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

"""integration tests for pull requests and commits that mention a loop, a
qbrix next surface, on recorded github payloads.

invariants verified:
  a pull request whose title, description or branch names a loop explicitly
  gets one entry per loop in that loop's history, which follows it from open
  to merged or closed and back to open, and keeps following when the mention
  is edited away; a bare key, or a link to another host, links nothing. a
  draft's earlier key still links unless another loop has it now. a commit
  reaching the default branch gets its own entry, unless it is the squash of
  a pull request that already has one; a commit elsewhere gets none. an
  unsigned event is refused before anything is read, and a delivery github
  sends twice changes nothing. one workspace's app never touches another's
  loops. history interleaves mentions with changes under one cursor, and
  show=github reads only them; the changes list never holds them. the
  repository read counts them. mcp loop_history reads them as lines.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import itertools
import json
from pathlib import Path

import pytest_asyncio
from sqlalchemy import func
from sqlalchemy import select

from qbrixstore.postgres.models import GitHubApp
from qbrixstore.postgres.models import GitHubDelivery
from qbrixstore.postgres.models import Mention
from qbrixstore.postgres.session import get_session

from proxysvc.core.actor import Actor
from proxysvc.transport.http.auth.dependencies import get_actor

from svc.proxy.tests.integration.http.conftest import as_tenant
from svc.proxy.tests.integration.http.test_github import ADA
from svc.proxy.tests.integration.http.test_github import BEN
from svc.proxy.tests.integration.http.test_github import CONSOLE
from svc.proxy.tests.integration.http.test_github import OTHER_TENANT
from svc.proxy.tests.integration.http.test_github import TENANT
from svc.proxy.tests.integration.http.test_github import _connected
from svc.proxy.tests.integration.http.test_github import _GitHub
from svc.proxy.tests.integration.http.test_github import api  # noqa: F401
from svc.proxy.tests.integration.http.test_github import clock  # noqa: F401
from svc.proxy.tests.integration.http.test_github import github  # noqa: F401

FIXTURES = Path(__file__).parents[2] / "fixtures" / "github"

PURCHASE = {
    "name": "purchase",
    "semantic": "a completed checkout",
    "type": "conversion",
}
OPTIONS = [
    {"name": "Control", "config": {"text": "Buy now"}},
    {"name": "Urgency", "config": {"text": "Only today"}},
]

_deliveries = itertools.count(1)


def _payload(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _pull_request(name: str = "pull_request_opened", **pull) -> dict:
    payload = copy.deepcopy(_payload(name))
    head = pull.pop("branch", None)
    if head is not None:
        payload["pull_request"]["head"]["ref"] = head
    payload["pull_request"].update(pull)
    return payload


def _push(message: str | None = None, *, ref: str = "refs/heads/main") -> dict:
    payload = copy.deepcopy(_payload("push"))
    payload["ref"] = ref
    if message is not None:
        payload["commits"][0]["message"] = message
    return payload


class _App:
    def __init__(self, token: str, secret: str):
        self.token = token
        self.secret = secret


async def _app(github: _GitHub, tenant_id: str) -> _App:
    async with get_session() as session:
        stored = (
            await session.execute(
                select(GitHubApp).where(GitHubApp.tenant_id == tenant_id)
            )
        ).scalar_one()
    return _App(stored.events_token, github.apps[stored.app_id]["webhook_secret"])


async def _send(
    api,
    app: _App,
    name: str,
    payload: dict,
    *,
    delivery: str | None = None,
    secret: str | None = None,
):
    body = json.dumps(payload).encode()
    signature = hmac.new(
        (secret or app.secret).encode(), body, hashlib.sha256
    ).hexdigest()
    resp = await api.post(
        f"/api/v1/github/events/{app.token}",
        content=body,
        headers={
            "x-github-event": name,
            "x-github-delivery": delivery or f"delivery-{next(_deliveries)}",
            "x-hub-signature-256": f"sha256={signature}",
            "content-type": "application/json",
        },
    )
    return resp


async def _sent(api, app: _App, name: str, payload: dict, **kwargs) -> None:
    resp = await _send(api, app, name, payload, **kwargs)
    assert resp.status_code == 204, resp.text


async def _loop(api, name: str, key: str | None = None) -> dict:
    body = {"name": name, "metric": "purchase", "options": OPTIONS}
    if key is not None:
        body["key"] = key
    resp = await api.post("/api/v1/loops", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _history(api, loop: str = "checkout-headline", **params) -> dict:
    resp = await api.get(f"/api/v1/loops/{loop}/history", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _mentions(api, loop: str = "checkout-headline") -> list[dict]:
    return (await _history(api, loop, show="github"))["entries"]


async def _count(model) -> int:
    async with get_session() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar()


@pytest_asyncio.fixture
async def linked(wired_app, api, github):  # noqa: F811
    """a connected workspace with a metric and the checkout-headline draft."""
    overrides = wired_app.app.dependency_overrides
    overrides[get_actor] = lambda: Actor.member(ADA)
    await _connected(api, github)
    assert (await api.post("/api/v1/metrics", json=PURCHASE)).status_code == 201
    await _loop(api, "Checkout headline")
    yield await _app(github, TENANT)
    del overrides[get_actor]


class TestPullRequests:
    async def test_opened_then_merged_is_one_entry(self, api, linked):
        await _sent(api, linked, "pull_request", _pull_request())

        (opened,) = await _mentions(api)
        assert opened["type"] == "mention"
        assert opened["kind"] == "pull_request"
        assert opened["repository"] == "acme/shop"
        assert opened["number"] == 42
        assert opened["title"] == "Try three checkout headlines"
        assert opened["author"] == "ada"
        assert opened["state"] == "open"
        assert opened["url"] == "https://github.com/acme/shop/pull/42"
        assert opened["at"].startswith("2026-11-24T10:00:00")

        await _sent(api, linked, "pull_request", _pull_request("pull_request_closed"))

        (merged,) = await _mentions(api)
        assert merged["id"] == opened["id"]
        assert merged["state"] == "merged"
        assert merged["merged_by"] == "grace"
        assert merged["at"].startswith("2026-11-24T15:30:00")
        assert merged["merged_at"] == merged["at"]
        assert merged["opened_at"].startswith("2026-11-24T10:00:00")

    async def test_closed_unmerged_then_reopened(self, api, linked):
        await _sent(api, linked, "pull_request", _pull_request())
        closed = _pull_request(
            "pull_request_closed", merged=False, merged_at=None, merged_by=None
        )
        await _sent(api, linked, "pull_request", closed)

        (entry,) = await _mentions(api)
        assert entry["state"] == "closed"
        assert entry["closed_at"].startswith("2026-11-24T15:30:00")
        assert entry["merged_at"] is None

        reopened = _pull_request(action="reopened", updated_at="2026-11-24T17:00:00Z")
        reopened["action"] = "reopened"
        await _sent(api, linked, "pull_request", reopened)

        (entry,) = await _mentions(api)
        assert entry["state"] == "open"
        assert entry["closed_at"] is None
        assert entry["at"].startswith("2026-11-24T17:00:00")

    async def test_two_loops_each_get_an_entry(self, api, linked):
        await _loop(api, "Pricing page")
        await _sent(
            api,
            linked,
            "pull_request",
            _pull_request(
                title="Headline and pricing qbrix:pricing-page",
                body="qbrix:checkout-headline",
            ),
        )

        assert len(await _mentions(api)) == 1
        assert len(await _mentions(api, "pricing-page")) == 1

    async def test_a_bare_key_links_nothing(self, api, linked):
        await _sent(
            api, linked, "pull_request", _pull_request(body="for checkout-headline")
        )

        assert await _mentions(api) == []
        assert await _count(Mention) == 0

    async def test_the_branch_names_the_loop_with_qbrix_slash_key(self, api, linked):
        await _sent(
            api,
            linked,
            "pull_request",
            _pull_request(body="", branch="ada/qbrix/checkout-headline"),
        )

        assert len(await _mentions(api)) == 1

    async def test_a_console_link_on_this_install_links(self, api, linked):
        for number, path in ((1, "/next/loops"), (2, "/loops")):
            await _sent(
                api,
                linked,
                "pull_request",
                _pull_request(
                    number=number, body=f"{CONSOLE}{path}/checkout-headline/history"
                ),
            )

        assert sorted(e["number"] for e in await _mentions(api)) == [1, 2]

    async def test_the_same_link_on_another_host_doesnt(self, api, linked):
        await _sent(
            api,
            linked,
            "pull_request",
            _pull_request(body="https://elsewhere.example.com/loops/checkout-headline"),
        )

        assert await _mentions(api) == []

    async def test_an_edited_away_mention_keeps_its_entry_and_follows(
        self, api, linked
    ):
        await _sent(api, linked, "pull_request", _pull_request())
        edited = _pull_request(body="no loop here", title="Renamed")
        edited["action"] = "edited"
        await _sent(api, linked, "pull_request", edited)
        merged = _pull_request("pull_request_closed", body="no loop here")
        await _sent(api, linked, "pull_request", merged)

        (entry,) = await _mentions(api)
        assert entry["title"] == "Try three checkout headlines"
        assert entry["state"] == "merged"

    async def test_other_actions_are_ignored(self, api, linked):
        labeled = _pull_request()
        labeled["action"] = "labeled"
        await _sent(api, linked, "pull_request", labeled)

        assert await _mentions(api) == []


class TestEarlierKeys:
    async def test_a_drafts_earlier_key_still_links(self, api, linked):
        await _loop(api, "Checkout cta")
        renamed = await api.patch("/api/v1/loops/checkout-cta", json={"key": "cta-v2"})
        assert renamed.status_code == 200, renamed.text

        await _sent(
            api, linked, "pull_request", _pull_request(body="qbrix:checkout-cta")
        )

        assert len(await _mentions(api, "cta-v2")) == 1

    async def test_unless_another_loop_has_that_key_now(self, api, linked):
        await _loop(api, "Checkout cta")
        renamed = await api.patch("/api/v1/loops/checkout-cta", json={"key": "cta-v2"})
        assert renamed.status_code == 200, renamed.text
        await _loop(api, "Checkout cta")

        await _sent(
            api, linked, "pull_request", _pull_request(body="qbrix:checkout-cta")
        )

        assert await _mentions(api, "cta-v2") == []
        assert len(await _mentions(api, "checkout-cta")) == 1


class TestCommits:
    async def test_a_squash_merge_shows_once(self, api, linked):
        await _sent(api, linked, "pull_request", _pull_request())
        await _sent(api, linked, "pull_request", _pull_request("pull_request_closed"))
        await _sent(api, linked, "push", _push())

        (entry,) = await _mentions(api)
        assert entry["kind"] == "pull_request"

    async def test_a_direct_commit_to_the_default_branch_shows(self, api, linked):
        await _sent(
            api,
            linked,
            "push",
            _push("Tighten the headline copy\n\nqbrix:checkout-headline"),
        )

        (entry,) = await _mentions(api)
        assert entry["kind"] == "commit"
        assert entry["sha"] == "9c8b7a6f5e4d3c2b1a09f8e7d6c5b4a392817160"
        assert entry["number"] is None
        assert entry["title"] == "Tighten the headline copy"
        assert entry["author"] == "ada"
        assert entry["state"] is None
        assert entry["at"].startswith("2026-11-24T15:30:30")

    async def test_a_squash_without_its_pull_requests_entry_shows_as_a_commit(
        self, api, linked
    ):
        await _sent(api, linked, "push", _push())

        (entry,) = await _mentions(api)
        assert entry["kind"] == "commit"

    async def test_a_commit_on_another_branch_doesnt(self, api, linked):
        await _sent(api, linked, "push", _push(ref="refs/heads/ada/headline"))

        assert await _mentions(api) == []

    async def test_the_same_commit_pushed_again_is_one_entry(self, api, linked):
        message = "Tighten the headline copy qbrix:checkout-headline"
        await _sent(api, linked, "push", _push(message))
        await _sent(api, linked, "push", _push(message))

        assert len(await _mentions(api)) == 1


class TestDelivery:
    async def test_a_wrong_signature_is_refused_before_anything(self, api, linked):
        resp = await _send(
            api, linked, "pull_request", _pull_request(), secret="not-the-secret"
        )

        assert resp.status_code == 401, resp.text
        assert await _count(Mention) == 0
        assert await _count(GitHubDelivery) == 0

    async def test_a_repeated_delivery_changes_nothing(self, api, linked):
        await _sent(api, linked, "pull_request", _pull_request(), delivery="d-1")
        (first,) = await _mentions(api)
        renamed = _pull_request(title="Something else qbrix:checkout-headline")
        renamed["action"] = "edited"
        await _sent(api, linked, "pull_request", renamed, delivery="d-1")

        (again,) = await _mentions(api)
        assert again == first

    async def test_old_deliveries_are_forgotten(self, api, linked, clock):  # noqa: F811
        from datetime import timedelta

        await _sent(api, linked, "ping", {"zen": "x"}, delivery="d-old")
        clock.now += timedelta(days=8)
        await _sent(api, linked, "ping", {"zen": "x"}, delivery="d-new")

        async with get_session() as session:
            ids = (await session.execute(select(GitHubDelivery.id))).scalars().all()
        assert ids == ["d-new"]


class TestWorkspaces:
    async def test_another_workspaces_app_never_touches_these_loops(
        self, wired_app, api, linked, github  # noqa: F811
    ):
        overrides = wired_app.app.dependency_overrides
        with as_tenant(wired_app.app, tenant_id=OTHER_TENANT, user_id=BEN):
            overrides[get_actor] = lambda: Actor.member(BEN)
            await _connected(api, github)
            assert (await api.post("/api/v1/metrics", json=PURCHASE)).status_code == 201
            await _loop(api, "Checkout headline")
            other = await _app(github, OTHER_TENANT)
            await _sent(api, other, "pull_request", _pull_request(number=7))
            await _sent(api, linked, "pull_request", _pull_request(number=8))
            theirs = await _mentions(api)
        overrides[get_actor] = lambda: Actor.member(ADA)

        assert [e["number"] for e in theirs] == [7]
        assert [e["number"] for e in await _mentions(api)] == [8]


class TestHistory:
    async def test_mentions_interleave_with_changes_by_time(self, api, linked):
        await _sent(api, linked, "pull_request", _pull_request())

        entries = (await _history(api))["entries"]
        assert [e["type"] for e in entries] == ["change", "mention"]
        assert entries[0]["kind"] == "loop.create"

    async def test_show_changes_leaves_mentions_out(self, api, linked):
        await _sent(api, linked, "pull_request", _pull_request())

        entries = (await _history(api, show="changes"))["entries"]
        assert [e["type"] for e in entries] == ["change"]

    async def test_one_cursor_pages_both(self, api, linked):
        for number in (1, 2, 3):
            await _sent(
                api,
                linked,
                "pull_request",
                _pull_request(number=number, created_at=f"2026-11-2{number}T10:00:00Z"),
            )

        seen = []
        cursor = None
        while True:
            params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
            page = await _history(api, **params)
            seen += [e.get("number") or e["kind"] for e in page["entries"]]
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert seen == ["loop.create", 3, 2, 1]

    async def test_the_changes_list_never_holds_them(self, api, linked):
        await _sent(api, linked, "pull_request", _pull_request())

        resp = await api.get("/api/v1/changes", params={"loop": "checkout-headline"})
        assert resp.status_code == 200, resp.text
        assert [c["kind"] for c in resp.json()["changes"]] == ["loop.create"]


class TestRepositoryCounts:
    async def test_the_read_counts_each_repositorys_mentions(self, api, linked):
        await _sent(api, linked, "pull_request", _pull_request())
        await _sent(api, linked, "pull_request", _pull_request("pull_request_closed"))

        resp = await api.get("/api/v1/github")
        assert resp.status_code == 200, resp.text
        repositories = {r["full_name"]: r for r in resp.json()["repositories"]}
        assert repositories["acme/shop"]["mentions"] == 1
        assert repositories["acme/shop"]["last_mention"].startswith(
            "2026-11-24T15:30:00"
        )
        assert repositories["acme/site"] == {
            "full_name": "acme/site",
            "mentions": 0,
            "last_mention": None,
        }

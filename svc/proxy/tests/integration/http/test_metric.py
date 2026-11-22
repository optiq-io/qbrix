"""integration tests for metrics, a qbrix next surface.

invariants verified:
  a metric is created at version 1.0 with its semantic, type and window (24
  hours unless given), and reads back by name or by id inside its workspace
  only. a score without a range, a range on any other type, an unknown type, a
  window of zero or less, and a name that is taken or not an identifier are
  refused, each with an error that names the problem. creating one records a
  single metric.create change, and undoing it deletes the metric.
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from qbrixstore.clickhouse.ledger import MetricArrival
from qbrixstore.clickhouse.ledger import MetricPulse
from qbrixstore.redis import OutcomeDisposition

import proxysvc.config
from proxysvc.core.actor import Actor
from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import ChangeNotUndoableError
from proxysvc.next import next_routes

from svc.proxy.tests.integration.http.conftest import as_tenant

TENANT = "dev-tenant"
UNDOER = Actor.member("user-undo", request_id="req-undo")

PURCHASE = {
    "name": "purchase",
    "semantic": "a completed checkout",
    "type": "conversion",
}


@pytest_asyncio.fixture
async def metrics(wired_app, client, next_enabled):
    """the client, with the next routes mounted on the app for this test only."""
    app = wired_app.app
    routes = list(app.router.routes)
    next_routes(app, proxysvc.config.settings)
    yield client
    app.router.routes[:] = routes


async def _create(client, **overrides) -> dict:
    resp = await client.post("/api/v1/metrics", json={**PURCHASE, **overrides})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _unstamped(metric: dict) -> dict:
    """a metric without its timestamps, which sqlite reads back without a zone."""
    return {k: v for k, v in metric.items() if k not in ("created_at", "updated_at")}


async def _changes(wired_app, metric_id: str) -> list[dict]:
    return await wired_app.svc.list_changes(TENANT, "metric", metric_id)


class TestCreate:
    async def test_starts_at_one_with_a_day_long_window(self, metrics):
        metric = await _create(metrics)

        assert metric["name"] == "purchase"
        assert metric["type"] == "conversion"
        assert metric["semantic"] == "a completed checkout"
        assert metric["version"] == "1.0"
        assert metric["window_seconds"] == 24 * 60 * 60
        assert metric["range"] is None

    async def test_keeps_the_window_it_is_given(self, metrics):
        metric = await _create(metrics, window_seconds=2 * 24 * 60 * 60)

        assert metric["window_seconds"] == 172800

    async def test_a_score_keeps_its_range(self, metrics):
        metric = await _create(
            metrics, name="csat", type="score", range={"lo": 1, "hi": 5}
        )

        assert metric["range"] == {"lo": 1.0, "hi": 5.0}


class TestRefusals:
    @pytest.mark.parametrize(
        "overrides, names",
        [
            ({"type": "score"}, "a score metric needs its declared range"),
            ({"range": {"lo": 0, "hi": 1}}, "a conversion metric has no range"),
            ({"type": "score", "range": {"lo": 5, "hi": 1}}, "lo below hi"),
            ({"type": "revenue"}, "unknown metric type 'revenue'"),
            ({"window_seconds": 0}, "a window is a positive number of seconds"),
            ({"window_seconds": -60}, "a window is a positive number of seconds"),
            ({"name": "Purchase"}, "a metric name is what code sends"),
            ({"name": "purchase completed"}, "a metric name is what code sends"),
            ({"name": "_purchase"}, "a metric name is what code sends"),
            ({"name": "p" * 65}, "a metric name is what code sends"),
            ({"semantic": "  "}, "a metric needs a semantic"),
        ],
    )
    async def test_names_the_problem(self, metrics, overrides, names):
        resp = await metrics.post("/api/v1/metrics", json={**PURCHASE, **overrides})

        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_METRIC"
        assert names in resp.json()["detail"]

    async def test_a_taken_name(self, metrics):
        await _create(metrics)

        resp = await metrics.post("/api/v1/metrics", json=PURCHASE)

        assert resp.status_code == 409
        assert resp.json()["code"] == "METRIC_NAME_TAKEN"
        assert "'purchase' already exists" in resp.json()["detail"]

    async def test_a_refusal_writes_nothing(self, metrics):
        await metrics.post("/api/v1/metrics", json={**PURCHASE, "type": "score"})

        resp = await metrics.get("/api/v1/metrics")

        assert resp.json()["metrics"] == []


class TestRead:
    async def test_by_name_and_by_id(self, metrics):
        created = await _create(metrics)

        by_name = await metrics.get("/api/v1/metrics/purchase")
        by_id = await metrics.get(f"/api/v1/metrics/{created['id']}")

        assert _unstamped(by_name.json()) == _unstamped(by_id.json())
        assert {
            k: v
            for k, v in _unstamped(by_name.json()).items()
            if k not in ("versions", "health")
        } == _unstamped(created)

    async def test_unknown_is_not_found(self, metrics):
        resp = await metrics.get("/api/v1/metrics/purchase")

        assert resp.status_code == 404
        assert resp.json()["code"] == "METRIC_NOT_FOUND"

    async def test_lists_every_metric_in_the_workspace_and_none_from_another(
        self, wired_app, metrics, tenant_a, tenant_b
    ):
        with as_tenant(wired_app.app, "tenant-a"):
            await _create(metrics)
            await _create(metrics, name="signup", semantic="an account created")
        with as_tenant(wired_app.app, "tenant-b"):
            await _create(metrics, name="click", semantic="a recommendation opened")

            other = await metrics.get("/api/v1/metrics")
            hidden = await metrics.get("/api/v1/metrics/purchase")
        with as_tenant(wired_app.app, "tenant-a"):
            own = await metrics.get("/api/v1/metrics")

        assert [m["name"] for m in own.json()["metrics"]] == ["purchase", "signup"]
        assert [m["name"] for m in other.json()["metrics"]] == ["click"]
        assert hidden.status_code == 404

    async def test_a_listed_metric_names_the_loops_that_use_it(self, metrics):
        await _create(metrics)
        await _create(metrics, name="signup", semantic="an account created")
        loop = await metrics.post(
            "/api/v1/loops",
            json={
                "name": "Checkout headline",
                "metric": "purchase",
                "options": [{"name": "A"}, {"name": "B"}],
            },
        )
        assert loop.status_code == 201, loop.text

        resp = await metrics.get("/api/v1/metrics")

        by_name = {m["name"]: m["loops"] for m in resp.json()["metrics"]}
        assert by_name["signup"] == []
        assert by_name["purchase"] == [
            {
                "id": loop.json()["id"],
                "key": "checkout-headline",
                "name": "Checkout headline",
                "state": "draft",
            }
        ]


def _last_minute() -> int:
    return int(time.time() * 1000) // 60_000 * 60_000 - 60_000


class TestHealth:
    async def test_a_listed_metric_carries_how_its_outcomes_arrive_now(
        self, wired_app, metrics
    ):
        purchase = await _create(metrics)
        await _create(metrics, name="signup", semantic="an account created")
        minute = _last_minute()
        wired_app.ledger.metric_arrival[purchase["id"]] = MetricArrival(
            purchase["id"], 200, 8, 90_000, 600_000, (0,) * 25
        )
        wired_app.ledger.pulse = [
            MetricPulse(purchase["id"], minute, 10),
            MetricPulse(purchase["id"], minute - 29 * 60_000, 3),
            MetricPulse(purchase["id"], minute - 30 * 60_000, 99),
        ]

        resp = await metrics.get("/api/v1/metrics")

        health = {m["name"]: m["health"] for m in resp.json()["metrics"]}
        assert health["purchase"] == {
            "outcomes_per_minute": 2.0,
            "median_wait_seconds": 90.0,
            "late_share": 0.04,
            "pulse": [3] + [0] * 28 + [10],
        }
        assert health["signup"] == {
            "outcomes_per_minute": 0.0,
            "median_wait_seconds": None,
            "late_share": None,
            "pulse": [0] * 30,
        }

    async def test_a_metrics_page_carries_arrival_and_seven_days_of_counts(
        self, wired_app, metrics
    ):
        purchase = await _create(metrics, window_seconds=2400)
        buckets = tuple(range(25))
        wired_app.ledger.metric_arrival[purchase["id"]] = MetricArrival(
            purchase["id"], 300, 24, 450_000, 2_100_000, buckets
        )
        redis = wired_app.svc._redis
        hour = int(time.time()) // 3600
        await redis.count_metric_outcomes(
            TENANT,
            purchase["id"],
            {OutcomeDisposition.LEARNED: 5, OutcomeDisposition.UNATTRIBUTED: 1},
            hour=hour - 100,
        )
        await redis.count_metric_outcomes(
            TENANT, purchase["id"], {OutcomeDisposition.INVALID: 2}
        )

        resp = await metrics.get("/api/v1/metrics/purchase")

        assert resp.json()["health"] == {
            "arrival": {
                "outcomes": 300,
                "bucket_seconds": 100.0,
                "buckets": list(buckets),
                "half_seconds": 450.0,
                "p99_seconds": 2100.0,
                "late_share": 0.08,
            },
            "counts": {
                "learned": 5,
                "late": 0,
                "duplicate": 0,
                "unattributed": 1,
                "invalid": 2,
            },
        }

    async def test_a_metric_with_no_outcomes_has_an_empty_arrival(self, metrics):
        await _create(metrics)

        resp = await metrics.get("/api/v1/metrics/purchase")

        arrival = resp.json()["health"]["arrival"]
        assert arrival["outcomes"] == 0
        assert arrival["buckets"] == [0] * 25
        assert arrival["half_seconds"] is None
        assert arrival["late_share"] is None

    async def test_fifty_metrics_list_from_two_queries_kept_a_minute(
        self, wired_app, metrics
    ):
        for n in range(50):
            await _create(metrics, name=f"metric_{n}")

        first = await metrics.get("/api/v1/metrics")
        await metrics.get("/api/v1/metrics")

        assert len(first.json()["metrics"]) == 50
        assert sorted(wired_app.ledger.queries) == ["metric_arrivals", "metric_pulse"]


class TestChange:
    async def test_create_is_one_change_with_its_actor_and_after(
        self, wired_app, metrics
    ):
        resp = await metrics.post(
            "/api/v1/metrics", json=PURCHASE, headers={"X-Request-ID": "req-metric"}
        )
        metric = resp.json()

        (change,) = await _changes(wired_app, metric["id"])

        assert change["kind"] == "metric.create"
        assert change["actor"]["kind"] == "member"
        assert change["actor"]["user_id"] == metric["created_by"]
        assert change["request_id"] == "req-metric"
        assert change["before"] is None
        assert change["after"] == metric
        assert change["undoable"] is True

    async def test_undo_deletes_the_metric(self, wired_app, metrics):
        metric = await _create(metrics)
        (create,) = await _changes(wired_app, metric["id"])

        undo = await wired_app.svc.undo_change(TENANT, create["id"], actor=UNDOER)

        assert undo["kind"] == "metric.delete"
        assert undo["undoes_id"] == create["id"]
        assert _unstamped(undo["before"]) == _unstamped(metric)
        assert undo["actor"]["user_id"] == "user-undo"
        resp = await metrics.get(f"/api/v1/metrics/{metric['id']}")
        assert resp.status_code == 404

    async def test_the_name_is_free_again_after_undo(self, wired_app, metrics):
        metric = await _create(metrics)
        (create,) = await _changes(wired_app, metric["id"])
        await wired_app.svc.undo_change(TENANT, create["id"], actor=UNDOER)

        again = await _create(metrics)

        assert again["id"] != metric["id"]

    async def test_undo_twice_is_refused(self, wired_app, metrics):
        metric = await _create(metrics)
        (create,) = await _changes(wired_app, metric["id"])
        await wired_app.svc.undo_change(TENANT, create["id"], actor=UNDOER)

        with pytest.raises(ChangeConflictError, match="already undone"):
            await wired_app.svc.undo_change(TENANT, create["id"], actor=UNDOER)

    async def test_the_delete_cannot_be_undone(self, wired_app, metrics):
        metric = await _create(metrics)
        (create,) = await _changes(wired_app, metric["id"])
        delete = await wired_app.svc.undo_change(TENANT, create["id"], actor=UNDOER)

        with pytest.raises(ChangeNotUndoableError, match="deleting a metric"):
            await wired_app.svc.undo_change(TENANT, delete["id"], actor=UNDOER)

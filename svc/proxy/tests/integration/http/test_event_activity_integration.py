"""integration tests for the per-experiment activity feed endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import proxysvc.transport.http.router.analytics.event as event_module
from svc.proxy.tests.integration.http.conftest import as_tenant

ACTIVITY_ROUTE = "/api/v1/event/experiment/exp-1/activity"
LEGACY_ACTIVITY_ROUTE = "/api/v1/ee/event/experiment/exp-1/activity"


def _sample_rows() -> list[dict]:
    """unified rows as returned by ClickHouseClient.query_events, newest first."""
    return [
        {
            "name": "feedback.received",
            "tenant_id": "tenant-a",
            "resource_id": "exp-1",
            "timestamp_ms": 3000,
            "category": "feedback",
            "data": {"request_id": "r-3", "arm_index": "1", "reward": "1.0"},
        },
        {
            "name": "selection.completed",
            "tenant_id": "tenant-a",
            "resource_id": "exp-1",
            "timestamp_ms": 2000,
            "category": "selection",
            "data": {"request_id": "r-2", "arm_id": "a-1", "policy": "beta_ts"},
        },
        {
            "name": "experiment.updated",
            "tenant_id": "tenant-a",
            "resource_id": "exp-1",
            "timestamp_ms": 1000,
            "category": "audit",
            "data": {"actor_id": "user-a", "resource_type": "experiment"},
        },
    ]


@pytest.fixture
def mock_clickhouse(monkeypatch):
    """patch the shared clickhouse client with a mock returning canned rows."""
    client = MagicMock()
    client.query_events = MagicMock(return_value=_sample_rows())
    monkeypatch.setattr(event_module, "get_clickhouse_client", lambda: client)
    return client


class TestExperimentActivity:

    async def test_legacy_path_answers_identically(
        self, client, wired_app, tenant_a, mock_clickhouse
    ):
        with as_tenant(
            wired_app.app, tenant_id=tenant_a.id, user_id="user-a", plan_tier="scale"
        ):
            current = await client.get(ACTIVITY_ROUTE)
            legacy = await client.get(LEGACY_ACTIVITY_ROUTE)

        assert current.status_code == legacy.status_code == 200
        assert legacy.json() == current.json()

    async def test_returns_unified_feed(
        self, client, wired_app, tenant_a, mock_clickhouse
    ):
        with as_tenant(
            wired_app.app, tenant_id=tenant_a.id, user_id="user-a", plan_tier="scale"
        ):
            response = await client.get(ACTIVITY_ROUTE)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["limit"] == 100
        assert body["offset"] == 0
        categories = [e["category"] for e in body["events"]]
        assert categories == ["feedback", "selection", "audit"]

    async def test_scopes_query_to_experiment_and_tenant(
        self, client, wired_app, tenant_a, mock_clickhouse
    ):
        with as_tenant(
            wired_app.app, tenant_id=tenant_a.id, user_id="user-a", plan_tier="scale"
        ):
            await client.get(
                ACTIVITY_ROUTE,
                params={"category": "feedback", "since_ms": 500, "limit": 10},
            )

        mock_clickhouse.query_events.assert_called_once_with(
            tenant_id=tenant_a.id,
            event_category="feedback",
            resource_id="exp-1",
            start_ms=500,
            end_ms=None,
            limit=10,
            offset=0,
        )

    async def test_until_ms_bounds_the_window(
        self, client, wired_app, tenant_a, mock_clickhouse
    ):
        """offset paging is only stable under an upper bound, so the console
        pins one before it walks back through the feed."""
        with as_tenant(
            wired_app.app, tenant_id=tenant_a.id, user_id="user-a", plan_tier="scale"
        ):
            await client.get(
                ACTIVITY_ROUTE, params={"until_ms": 2500, "limit": 10, "offset": 10}
            )

        mock_clickhouse.query_events.assert_called_once_with(
            tenant_id=tenant_a.id,
            event_category=None,
            resource_id="exp-1",
            start_ms=None,
            end_ms=2500,
            limit=10,
            offset=10,
        )

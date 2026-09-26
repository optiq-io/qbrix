"""unit tests for the workspace-wide EE insight router."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from proxysvc.transport.http.router.analytics.insight.tenant import (
    get_workspace_arm_stats,
)
from proxysvc.transport.http.router.analytics.insight.tenant import (
    WorkspaceArmStatsResponse,
)

TENANT_ID = "t-1"
DEV_USER = MagicMock()

MODULE = "proxysvc.transport.http.router.analytics.insight.tenant"


def _arm(index: int, name: str, selections: int, feedback: int, reward_sum: float):
    return {
        "arm_index": index,
        "arm_name": name,
        "selections": selections,
        "feedback_count": feedback,
        "reward_sum": reward_sum,
    }


async def _call(query_plan, batch):
    client = MagicMock()
    client.get_arm_stats_batch.return_value = batch

    async def _plan(tenant_id):
        return query_plan

    with (
        patch(f"{MODULE}._query_plan", side_effect=_plan),
        patch(f"{MODULE}.get_clickhouse_client", return_value=client),
    ):
        result = await get_workspace_arm_stats(
            start_ms=None,
            end_ms=None,
            tenant_id=TENANT_ID,
            _user=DEV_USER,
        )
    return result, client


class TestWorkspaceArmStats:

    @pytest.mark.asyncio
    async def test_groups_arms_by_experiment(self):
        result, _ = await _call(
            (["exp-1", "exp-2"], {"exp-1": "exp-1", "exp-2": "exp-2"}),
            {
                "exp-1": [_arm(0, "a", 100, 10, 4.0), _arm(1, "b", 50, 5, 1.0)],
                "exp-2": [_arm(0, "x", 7, 0, 0.0)],
            },
        )

        assert isinstance(result, WorkspaceArmStatsResponse)
        by_id = {e.experiment_id: e for e in result.experiments}
        assert set(by_id) == {"exp-1", "exp-2"}
        assert [a.arm_name for a in by_id["exp-1"].arms] == ["a", "b"]
        assert by_id["exp-1"].arms[0].avg_reward == pytest.approx(0.4)
        assert by_id["exp-1"].arms[1].avg_reward == pytest.approx(0.2)

    @pytest.mark.asyncio
    async def test_arm_with_no_feedback_reports_null_reward(self):
        result, _ = await _call(
            (["exp-1"], {"exp-1": "exp-1"}),
            {"exp-1": [_arm(0, "a", 12, 0, 0.0)]},
        )

        arm = result.experiments[0].arms[0]
        assert arm.selections == 12
        assert arm.feedback_count == 0
        assert arm.avg_reward is None

    @pytest.mark.asyncio
    async def test_meta_bandit_learners_fold_into_the_parent(self):
        """the parent carries no events of its own — the learners do."""
        result, _ = await _call(
            (
                ["meta-1", "learn-a", "learn-b"],
                {"meta-1": "meta-1", "learn-a": "meta-1", "learn-b": "meta-1"},
            ),
            {
                "learn-a": [_arm(0, "red", 100, 10, 5.0)],
                "learn-b": [_arm(0, "red", 300, 30, 9.0)],
            },
        )

        assert len(result.experiments) == 1
        experiment = result.experiments[0]
        assert experiment.experiment_id == "meta-1"
        assert len(experiment.arms) == 1
        arm = experiment.arms[0]
        assert arm.selections == 400
        assert arm.feedback_count == 40
        # summed reward over summed feedback — not the mean of the two means
        assert arm.avg_reward == pytest.approx(14.0 / 40)

    @pytest.mark.asyncio
    async def test_rows_for_an_unknown_experiment_are_dropped(self):
        """an id clickhouse still holds but postgres no longer lists."""
        result, _ = await _call(
            (["exp-1"], {"exp-1": "exp-1"}),
            {
                "exp-1": [_arm(0, "a", 1, 0, 0.0)],
                "deleted-1": [_arm(0, "z", 9, 1, 1.0)],
            },
        )

        assert [e.experiment_id for e in result.experiments] == ["exp-1"]

    @pytest.mark.asyncio
    async def test_empty_workspace_never_queries_clickhouse(self):
        result, client = await _call(([], {}), {})

        assert result.experiments == []
        client.get_arm_stats_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_window_is_forwarded_to_the_batch_query(self):
        client = MagicMock()
        client.get_arm_stats_batch.return_value = {}

        async def _plan(tenant_id):
            return (["exp-1"], {"exp-1": "exp-1"})

        with (
            patch(f"{MODULE}._query_plan", side_effect=_plan),
            patch(f"{MODULE}.get_clickhouse_client", return_value=client),
        ):
            await get_workspace_arm_stats(
                start_ms=111,
                end_ms=222,
                tenant_id=TENANT_ID,
                _user=DEV_USER,
            )

        kwargs = client.get_arm_stats_batch.call_args.kwargs
        assert kwargs["tenant_id"] == TENANT_ID
        assert kwargs["experiment_ids"] == ["exp-1"]
        assert kwargs["start_ms"] == 111
        assert kwargs["end_ms"] == 222

"""unit tests for EE insight router handlers."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from proxysvc.transport.http.router.analytics.insight.experiment import (
    get_reward_timeseries,
)
from proxysvc.transport.http.router.analytics.insight.experiment import (
    get_arm_timeseries,
)
from proxysvc.transport.http.router.analytics.insight.experiment import (
    get_feedback_funnel,
)
from proxysvc.transport.http.router.analytics.insight.experiment import (
    get_cumulative_reward,
)
from proxysvc.transport.http.router.analytics.insight.experiment import (
    RewardTimeseriesResponse,
)
from proxysvc.transport.http.router.analytics.insight.experiment import (
    ArmTimeseriesResponse,
)
from proxysvc.transport.http.router.analytics.insight.experiment import (
    FeedbackFunnelResponse,
)
from proxysvc.transport.http.router.analytics.insight.experiment import (
    CumulativeRewardResponse,
)


def _make_clickhouse_client(**method_returns):
    """create a mock clickhouse client with configurable return values."""
    client = MagicMock()
    for method_name, return_value in method_returns.items():
        getattr(client, method_name).return_value = return_value
    return client


TENANT_ID = "t-1"
EXPERIMENT_ID = "exp-1"
USER_ID = "u-1"
DEV_USER = MagicMock()


@pytest.fixture(autouse=True)
def _mock_resolve_experiment_ids():
    """bypass db-dependent resolver — return experiment_id as-is."""

    async def _passthrough(tenant_id, experiment_id):
        return experiment_id

    with patch(
        "proxysvc.transport.http.router.analytics.insight.experiment._resolve_experiment_ids",
        side_effect=_passthrough,
    ):
        yield


class TestGetRewardTimeseries:

    @pytest.mark.asyncio
    async def test_returns_correct_response_shape(self):
        mock_data = [
            {"timestamp_ms": 1000000, "avg_reward": 0.75, "feedback_count": 10},
            {"timestamp_ms": 2000000, "avg_reward": 0.80, "feedback_count": 15},
        ]
        mock_client = _make_clickhouse_client(get_reward_timeseries=mock_data)

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            result = await get_reward_timeseries(
                experiment_id=EXPERIMENT_ID,
                interval_ms=3600000,
                start_ms=None,
                end_ms=None,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                _user=DEV_USER,
            )

        assert isinstance(result, RewardTimeseriesResponse)
        assert len(result.data) == 2
        assert result.data[0].timestamp_ms == 1000000
        assert result.data[0].avg_reward == 0.75
        assert result.data[0].feedback_count == 10
        assert result.data[1].timestamp_ms == 2000000
        assert result.data[1].avg_reward == 0.80
        assert result.data[1].feedback_count == 15

    @pytest.mark.asyncio
    async def test_empty_data_returns_empty_list(self):
        mock_client = _make_clickhouse_client(get_reward_timeseries=[])

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            result = await get_reward_timeseries(
                experiment_id=EXPERIMENT_ID,
                interval_ms=3600000,
                start_ms=None,
                end_ms=None,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                _user=DEV_USER,
            )

        assert isinstance(result, RewardTimeseriesResponse)
        assert result.data == []

    @pytest.mark.asyncio
    async def test_passes_time_filters_to_client(self):
        mock_client = _make_clickhouse_client(get_reward_timeseries=[])

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            await get_reward_timeseries(
                experiment_id=EXPERIMENT_ID,
                interval_ms=3600000,
                start_ms=1000,
                end_ms=9000,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                _user=DEV_USER,
            )

        mock_client.get_reward_timeseries.assert_called_once_with(
            tenant_id=TENANT_ID,
            experiment_id=EXPERIMENT_ID,
            interval_ms=3600000,
            start_ms=1000,
            end_ms=9000,
        )

    @pytest.mark.asyncio
    async def test_client_exception_raises_internal_server_error(self):
        from proxysvc.transport.http.exception import InternalServerException

        mock_client = MagicMock()
        mock_client.get_reward_timeseries.side_effect = RuntimeError("clickhouse down")

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            with pytest.raises(InternalServerException):
                await get_reward_timeseries(
                    experiment_id=EXPERIMENT_ID,
                    interval_ms=3600000,
                    start_ms=None,
                    end_ms=None,
                    tenant_id=TENANT_ID,
                    user_id=USER_ID,
                    _user=DEV_USER,
                )


class TestGetArmTimeseries:

    @pytest.mark.asyncio
    async def test_returns_correct_response_shape(self):
        mock_data = [
            {
                "timestamp_ms": 1000000,
                "arms": [
                    {"arm_index": 0, "arm_name": "control", "selections": 5},
                    {"arm_index": 1, "arm_name": "variant", "selections": 8},
                ],
            },
        ]
        mock_client = _make_clickhouse_client(get_arm_timeseries=mock_data)

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            result = await get_arm_timeseries(
                experiment_id=EXPERIMENT_ID,
                interval_ms=3600000,
                start_ms=None,
                end_ms=None,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                _user=DEV_USER,
            )

        assert isinstance(result, ArmTimeseriesResponse)
        assert len(result.data) == 1
        assert result.data[0].timestamp_ms == 1000000
        assert len(result.data[0].arms) == 2
        assert result.data[0].arms[0].arm_index == 0
        assert result.data[0].arms[0].arm_name == "control"
        assert result.data[0].arms[0].selections == 5
        assert result.data[0].arms[1].arm_index == 1
        assert result.data[0].arms[1].arm_name == "variant"
        assert result.data[0].arms[1].selections == 8

    @pytest.mark.asyncio
    async def test_empty_data_returns_empty_list(self):
        mock_client = _make_clickhouse_client(get_arm_timeseries=[])

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            result = await get_arm_timeseries(
                experiment_id=EXPERIMENT_ID,
                interval_ms=3600000,
                start_ms=None,
                end_ms=None,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                _user=DEV_USER,
            )

        assert isinstance(result, ArmTimeseriesResponse)
        assert result.data == []

    @pytest.mark.asyncio
    async def test_passes_time_filters_to_client(self):
        mock_client = _make_clickhouse_client(get_arm_timeseries=[])

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            await get_arm_timeseries(
                experiment_id=EXPERIMENT_ID,
                interval_ms=3600000,
                start_ms=500,
                end_ms=8000,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                _user=DEV_USER,
            )

        mock_client.get_arm_timeseries.assert_called_once_with(
            tenant_id=TENANT_ID,
            experiment_id=EXPERIMENT_ID,
            interval_ms=3600000,
            start_ms=500,
            end_ms=8000,
        )

    @pytest.mark.asyncio
    async def test_client_exception_raises_internal_server_error(self):
        from proxysvc.transport.http.exception import InternalServerException

        mock_client = MagicMock()
        mock_client.get_arm_timeseries.side_effect = RuntimeError("clickhouse down")

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            with pytest.raises(InternalServerException):
                await get_arm_timeseries(
                    experiment_id=EXPERIMENT_ID,
                    interval_ms=3600000,
                    start_ms=None,
                    end_ms=None,
                    tenant_id=TENANT_ID,
                    user_id=USER_ID,
                    _user=DEV_USER,
                )


class TestGetFeedbackFunnel:

    @pytest.mark.asyncio
    async def test_returns_correct_response_shape(self):
        mock_funnel = {
            "total_selections": 1000,
            "total_feedback": 750,
            "feedback_rate": 0.75,
        }
        mock_client = _make_clickhouse_client(get_feedback_funnel=mock_funnel)

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            result = await get_feedback_funnel(
                experiment_id=EXPERIMENT_ID,
                start_ms=None,
                end_ms=None,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                _user=DEV_USER,
            )

        assert isinstance(result, FeedbackFunnelResponse)
        assert result.total_selections == 1000
        assert result.total_feedback == 750
        assert result.feedback_rate == 0.75

    @pytest.mark.asyncio
    async def test_zero_selections_returns_zero_rate(self):
        mock_funnel = {
            "total_selections": 0,
            "total_feedback": 0,
            "feedback_rate": 0.0,
        }
        mock_client = _make_clickhouse_client(get_feedback_funnel=mock_funnel)

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            result = await get_feedback_funnel(
                experiment_id=EXPERIMENT_ID,
                start_ms=None,
                end_ms=None,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                _user=DEV_USER,
            )

        assert result.feedback_rate == 0.0

    @pytest.mark.asyncio
    async def test_passes_time_filters_to_client(self):
        mock_funnel = {"total_selections": 0, "total_feedback": 0, "feedback_rate": 0.0}
        mock_client = _make_clickhouse_client(get_feedback_funnel=mock_funnel)

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            await get_feedback_funnel(
                experiment_id=EXPERIMENT_ID,
                start_ms=100,
                end_ms=200,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                _user=DEV_USER,
            )

        mock_client.get_feedback_funnel.assert_called_once_with(
            tenant_id=TENANT_ID,
            experiment_id=EXPERIMENT_ID,
            start_ms=100,
            end_ms=200,
        )

    @pytest.mark.asyncio
    async def test_client_exception_raises_internal_server_error(self):
        from proxysvc.transport.http.exception import InternalServerException

        mock_client = MagicMock()
        mock_client.get_feedback_funnel.side_effect = RuntimeError("clickhouse down")

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            with pytest.raises(InternalServerException):
                await get_feedback_funnel(
                    experiment_id=EXPERIMENT_ID,
                    start_ms=None,
                    end_ms=None,
                    tenant_id=TENANT_ID,
                    user_id=USER_ID,
                    _user=DEV_USER,
                )


class TestGetCumulativeReward:

    @pytest.mark.asyncio
    async def test_returns_correct_response_shape(self):
        mock_data = [
            {"timestamp_ms": 1000000, "cumulative_reward": 10.5, "cumulative_count": 5},
            {
                "timestamp_ms": 2000000,
                "cumulative_reward": 22.0,
                "cumulative_count": 11,
            },
        ]
        mock_client = _make_clickhouse_client(get_cumulative_reward=mock_data)

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            result = await get_cumulative_reward(
                experiment_id=EXPERIMENT_ID,
                interval_ms=3600000,
                start_ms=None,
                end_ms=None,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                _user=DEV_USER,
            )

        assert isinstance(result, CumulativeRewardResponse)
        assert len(result.data) == 2
        assert result.data[0].timestamp_ms == 1000000
        assert result.data[0].cumulative_reward == 10.5
        assert result.data[0].cumulative_count == 5
        assert result.data[1].timestamp_ms == 2000000
        assert result.data[1].cumulative_reward == 22.0
        assert result.data[1].cumulative_count == 11

    @pytest.mark.asyncio
    async def test_empty_data_returns_empty_list(self):
        mock_client = _make_clickhouse_client(get_cumulative_reward=[])

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            result = await get_cumulative_reward(
                experiment_id=EXPERIMENT_ID,
                interval_ms=3600000,
                start_ms=None,
                end_ms=None,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                _user=DEV_USER,
            )

        assert isinstance(result, CumulativeRewardResponse)
        assert result.data == []

    @pytest.mark.asyncio
    async def test_passes_time_filters_to_client(self):
        mock_client = _make_clickhouse_client(get_cumulative_reward=[])

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            await get_cumulative_reward(
                experiment_id=EXPERIMENT_ID,
                interval_ms=3600000,
                start_ms=1000,
                end_ms=9000,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                _user=DEV_USER,
            )

        mock_client.get_cumulative_reward.assert_called_once_with(
            tenant_id=TENANT_ID,
            experiment_id=EXPERIMENT_ID,
            interval_ms=3600000,
            start_ms=1000,
            end_ms=9000,
        )

    @pytest.mark.asyncio
    async def test_client_exception_raises_internal_server_error(self):
        from proxysvc.transport.http.exception import InternalServerException

        mock_client = MagicMock()
        mock_client.get_cumulative_reward.side_effect = RuntimeError("clickhouse down")

        with patch(
            "proxysvc.transport.http.router.analytics.insight.experiment.get_clickhouse_client",
            return_value=mock_client,
        ):
            with pytest.raises(InternalServerException):
                await get_cumulative_reward(
                    experiment_id=EXPERIMENT_ID,
                    interval_ms=3600000,
                    start_ms=None,
                    end_ms=None,
                    tenant_id=TENANT_ID,
                    user_id=USER_ID,
                    _user=DEV_USER,
                )

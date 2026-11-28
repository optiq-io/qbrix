"""with next on, today's pool, experiment, select and feedback calls fail
their precondition over grpc, saying to create a loop."""

from __future__ import annotations

from unittest.mock import MagicMock

import grpc
import pytest

from qbrixproto import common_pb2
from qbrixproto import proxy_pb2

from proxysvc.core.error import REPLACED_BY_LOOPS
from proxysvc.core.error import ReplacedByLoopsError
from proxysvc.transport.grpc.exception.interceptor import _map_domain_error


class TestGrpc:
    async def test_old_calls_fail_their_precondition(self, wired_grpc, monkeypatch):
        monkeypatch.setattr(wired_grpc.svc._settings, "next_enabled", True)
        calls = [
            (
                "CreatePool",
                proxy_pb2.CreatePoolRequest(name="p", arms=[common_pb2.Arm(name="a")]),
            ),
            ("UpdatePool", proxy_pb2.UpdatePoolRequest(pool_id="p", name="x")),
            ("DeletePool", proxy_pb2.DeletePoolRequest(pool_id="p")),
            (
                "CreateExperiment",
                proxy_pb2.CreateExperimentRequest(
                    name="e", pool_id="p", policy="RandomPolicy"
                ),
            ),
            (
                "UpdateExperiment",
                proxy_pb2.UpdateExperimentRequest(experiment_id="e", enabled=False),
            ),
            ("DeleteExperiment", proxy_pb2.DeleteExperimentRequest(experiment_id="e")),
            ("Select", proxy_pb2.SelectRequest(experiment_id="e")),
            ("Feedback", proxy_pb2.FeedbackRequest(request_id="r", reward=1.0)),
        ]
        for name, request in calls:
            with pytest.raises(ReplacedByLoopsError):
                await getattr(wired_grpc.servicer, name)(request, MagicMock())

        mapped = _map_domain_error(ReplacedByLoopsError())
        assert mapped.status_code == grpc.StatusCode.FAILED_PRECONDITION
        assert mapped.detail == REPLACED_BY_LOOPS

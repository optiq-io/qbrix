"""unit tests for ProxyGRPCServicer.ListPolicies."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from google.protobuf import struct_pb2

from qbrixcore.policy import POLICIES
from qbrixcore.policy import RewardType
from qbrixproto import proxy_pb2

from proxysvc.transport.grpc.exception.base import InvalidArgumentException
from proxysvc.server import ProxyGRPCServicer


@pytest.fixture
def servicer():
    return ProxyGRPCServicer(MagicMock())


@pytest.fixture
def grpc_context():
    ctx = MagicMock()
    return ctx


class TestListPoliciesUnfiltered:
    """unfiltered request returns all policies."""

    async def test_returns_all_policies(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest()
        result = await servicer.ListPolicies(request, grpc_context)
        assert len(result.policies) == len(POLICIES)

    async def test_beta_ts_name(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest()
        result = await servicer.ListPolicies(request, grpc_context)
        names = [p.name for p in result.policies]
        assert "BetaTSPolicy" in names

    async def test_beta_ts_category(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest()
        result = await servicer.ListPolicies(request, grpc_context)
        beta = next(p for p in result.policies if p.name == "BetaTSPolicy")
        assert beta.category == "stochastic"

    async def test_beta_ts_reward_types_nonempty(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest()
        result = await servicer.ListPolicies(request, grpc_context)
        beta = next(p for p in result.policies if p.name == "BetaTSPolicy")
        assert len(beta.reward_types) > 0
        assert "binary" in beta.reward_types

    async def test_beta_ts_description_nonempty(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest()
        result = await servicer.ListPolicies(request, grpc_context)
        beta = next(p for p in result.policies if p.name == "BetaTSPolicy")
        assert beta.description != ""
        assert "Thompson" in beta.description


class TestListPoliciesFilterByRewardType:
    """reward_type filter returns only matching policies."""

    async def test_binary_filter_returns_only_binary_policies(
        self, servicer, grpc_context
    ):
        request = proxy_pb2.ListPoliciesRequest(reward_type="binary")
        result = await servicer.ListPolicies(request, grpc_context)
        expected = [p for p in POLICIES if RewardType.BINARY in p.reward_types]
        assert len(result.policies) == len(expected)
        for proto_policy in result.policies:
            assert "binary" in proto_policy.reward_types

    async def test_bounded_filter(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest(reward_type="bounded")
        result = await servicer.ListPolicies(request, grpc_context)
        expected = [p for p in POLICIES if RewardType.BOUNDED in p.reward_types]
        assert len(result.policies) == len(expected)
        for proto_policy in result.policies:
            assert "bounded" in proto_policy.reward_types

    async def test_continuous_filter(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest(reward_type="continuous")
        result = await servicer.ListPolicies(request, grpc_context)
        expected = [p for p in POLICIES if RewardType.CONTINUOUS in p.reward_types]
        assert len(result.policies) == len(expected)
        for proto_policy in result.policies:
            assert "continuous" in proto_policy.reward_types

    async def test_binary_filter_is_subset_of_all(self, servicer, grpc_context):
        all_req = proxy_pb2.ListPoliciesRequest()
        all_result = await servicer.ListPolicies(all_req, grpc_context)

        bin_req = proxy_pb2.ListPoliciesRequest(reward_type="binary")
        bin_result = await servicer.ListPolicies(bin_req, grpc_context)

        assert len(bin_result.policies) < len(all_result.policies)


class TestListPoliciesInvalidRewardType:
    """invalid reward_type raises InvalidArgumentException."""

    async def test_garbage_raises_invalid_argument(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest(reward_type="garbage")
        with pytest.raises(InvalidArgumentException):
            await servicer.ListPolicies(request, grpc_context)

    async def test_uppercase_raises_invalid_argument(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest(reward_type="BINARY")
        with pytest.raises(InvalidArgumentException):
            await servicer.ListPolicies(request, grpc_context)

    async def test_partial_raises_invalid_argument(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest(reward_type="bin")
        with pytest.raises(InvalidArgumentException):
            await servicer.ListPolicies(request, grpc_context)


class TestListPoliciesUserParams:
    """policies with configurable params produce populated PolicyParam entries."""

    async def test_epsilon_policy_has_user_params(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest()
        result = await servicer.ListPolicies(request, grpc_context)
        eps = next(p for p in result.policies if p.name == "EpsilonPolicy")
        assert len(eps.user_params) > 0

    async def test_epsilon_eps_param_name_and_type(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest()
        result = await servicer.ListPolicies(request, grpc_context)
        eps = next(p for p in result.policies if p.name == "EpsilonPolicy")
        param_names = [p.name for p in eps.user_params]
        assert "eps" in param_names

    async def test_epsilon_eps_param_required(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest()
        result = await servicer.ListPolicies(request, grpc_context)
        eps = next(p for p in result.policies if p.name == "EpsilonPolicy")
        eps_param = next(p for p in eps.user_params if p.name == "eps")
        assert eps_param.required is True

    async def test_epsilon_eps_param_type_is_number(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest()
        result = await servicer.ListPolicies(request, grpc_context)
        eps = next(p for p in result.policies if p.name == "EpsilonPolicy")
        eps_param = next(p for p in eps.user_params if p.name == "eps")
        assert eps_param.type == "number"

    async def test_epsilon_eps_param_default_is_null_value(
        self, servicer, grpc_context
    ):
        # eps has no default (required=True, default=None) -> null_value
        request = proxy_pb2.ListPoliciesRequest()
        result = await servicer.ListPolicies(request, grpc_context)
        eps = next(p for p in result.policies if p.name == "EpsilonPolicy")
        eps_param = next(p for p in eps.user_params if p.name == "eps")
        assert eps_param.default.WhichOneof("kind") == "null_value"

    async def test_epsilon_eps_param_constraints(self, servicer, grpc_context):
        request = proxy_pb2.ListPoliciesRequest()
        result = await servicer.ListPolicies(request, grpc_context)
        eps = next(p for p in result.policies if p.name == "EpsilonPolicy")
        eps_param = next(p for p in eps.user_params if p.name == "eps")
        assert "gte" in eps_param.constraints
        assert "lte" in eps_param.constraints
        assert eps_param.constraints["gte"] == 0.0
        assert eps_param.constraints["lte"] == 1.0


class TestToProtoValue:
    """_to_proto_value handles all primitive types correctly."""

    def test_none_produces_null_value(self):
        v = ProxyGRPCServicer._to_proto_value(None)
        assert v.WhichOneof("kind") == "null_value"

    def test_int_produces_number_value(self):
        v = ProxyGRPCServicer._to_proto_value(3)
        assert v.WhichOneof("kind") == "number_value"
        assert v.number_value == 3.0

    def test_float_produces_number_value(self):
        v = ProxyGRPCServicer._to_proto_value(0.5)
        assert v.WhichOneof("kind") == "number_value"
        assert v.number_value == 0.5

    def test_str_produces_string_value(self):
        v = ProxyGRPCServicer._to_proto_value("hello")
        assert v.WhichOneof("kind") == "string_value"
        assert v.string_value == "hello"

    def test_bool_produces_bool_value(self):
        v = ProxyGRPCServicer._to_proto_value(True)
        assert v.WhichOneof("kind") == "bool_value"
        assert v.bool_value is True

    def test_other_produces_json_string(self):
        v = ProxyGRPCServicer._to_proto_value([1, 2])
        assert v.WhichOneof("kind") == "string_value"
        import json

        assert json.loads(v.string_value) == [1, 2]

    def test_returns_struct_pb2_value(self):
        v = ProxyGRPCServicer._to_proto_value(42)
        assert isinstance(v, struct_pb2.Value)


class TestListPoliciesNoTenantNeeded:
    """ListPolicies is stateless — no auth context required."""

    async def test_works_without_auth_context(self, servicer, grpc_context):
        # do not set GRPCAuthContext — method must not call _get_tenant_id
        from proxysvc.transport.grpc.auth.context import set_grpc_auth_context

        set_grpc_auth_context(None)
        request = proxy_pb2.ListPoliciesRequest()
        result = await servicer.ListPolicies(request, grpc_context)
        assert len(result.policies) == len(POLICIES)

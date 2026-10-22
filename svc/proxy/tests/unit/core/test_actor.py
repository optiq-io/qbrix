"""unit tests for the actor a change is recorded with."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qbrixlog.context import request_context

from proxysvc.core.actor import Actor
from proxysvc.core.actor import inbound_request_id
from proxysvc.transport.http.auth.dependencies import get_actor


class TestInboundRequestId:
    @pytest.mark.parametrize("value", ["abc", "req-1.2_3", "x" * 64])
    def test_a_safe_id_is_kept(self, value):
        assert inbound_request_id(value) == value

    @pytest.mark.parametrize("value", [None, "", "a b", "x" * 65, "id\nforged"])
    def test_anything_else_is_replaced(self, value):
        minted = inbound_request_id(value)
        assert minted != value
        assert len(minted) == 32


class TestGetActor:
    async def test_a_jwt_request_is_the_member_alone(self):
        request = SimpleNamespace(state=SimpleNamespace(api_key=None))
        with request_context("req-1"):
            actor = await get_actor(request, user_id="u-1")

        assert actor == Actor(kind="member", user_id="u-1", request_id="req-1")

    async def test_an_api_key_request_records_the_key(self):
        request = SimpleNamespace(
            state=SimpleNamespace(api_key=SimpleNamespace(id="k-1"))
        )
        actor = await get_actor(request, user_id="u-1")

        assert actor.api_key_id == "k-1"
        assert actor.user_id == "u-1"

    async def test_dev_mode_sets_no_api_key(self):
        request = SimpleNamespace(state=SimpleNamespace())
        actor = await get_actor(request, user_id="dev-user")

        assert actor.user_id == "dev-user"
        assert actor.api_key_id == ""

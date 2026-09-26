"""http integration tests for agent router.

invariants verified:
  scenario 1: POST /agent/select, no gate hit → motor called, response has
              request_id + is_default=False, SelectionEvent published with matching arm
  scenario 2: POST /agent/select, gate hit → motor NOT called, is_default=True,
              SelectionEvent.policy == "gate"
  scenario 3: POST /agent/select, meta-bandit → published SelectionEvent.experiment_id
              equals the learner id, not the parent id
  scenario 4: POST /agent/feedback with a valid token → FeedbackEvent published
              with arm_index matching prior selection
  scenario 5: POST /agent/feedback with a tampered token → 4xx, no FeedbackEvent
  scenario 6: POST /agent/select with a wrong-width or absent context vector on a
              contextual experiment → 400 INVALID_CONTEXT_VECTOR, motor never called
  scenario 8: POST /agent/select with context.properties on a schema-backed
              experiment → encoded at the edge, motor sees only a vector, and the
              same vector round-trips through the token to the FeedbackEvent
"""

from __future__ import annotations

import pytest

from qbrixstore.event import FeedbackEvent
from qbrixstore.event import SelectionEvent

from proxysvc.mod.gate.config import FeatureGateConfig
from proxysvc.mod.gate.model.base import ArmConfig
from proxysvc.mod.gate.model.base import BaseArmModel
from proxysvc.mod.gate import ExperimentConfig
from proxysvc.mod.gate.model.rule import Rule

# ── helpers ───────────────────────────────────────────────────────────────────


async def _create_pool(client, *, name: str = "agent-pool") -> tuple[str, list[dict]]:
    """create a 2-arm pool, return (pool_id, arms list)."""
    resp = await client.post(
        "/api/v1/pools",
        json={
            "name": name,
            "arms": [
                {"name": "control", "metadata": {}},
                {"name": "variant", "metadata": {}},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return data["id"], data["arms"]


async def _create_experiment(
    client,
    pool_id: str,
    *,
    name: str = "agent-exp",
    policy: str = "RandomPolicy",
    policy_params: dict | None = None,
) -> dict:
    """create an experiment and return the response json."""
    resp = await client.post(
        "/api/v1/experiments",
        json={
            "name": name,
            "pool_id": pool_id,
            "policy": policy,
            "policy_params": policy_params or {},
            "enabled": True,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── scenario 1 ────────────────────────────────────────────────────────────────


class TestSelectNoGateHit:
    async def test_select_calls_motor_and_publishes_selection_event(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: POST /agent/select when no gate is configured routes to motorsvc,
        returns a signed request_id and is_default=False, and publishes exactly one
        SelectionEvent whose arm_id matches what motor returned.  no FeedbackEvent
        is published on select.
        """
        pool_id, arms = await _create_pool(client, name="select-no-gate-pool")
        exp_data = await _create_experiment(client, pool_id, name="select-no-gate-exp")
        exp_id = exp_data["id"]
        arm = arms[0]

        # motor returns the first arm — matches MotorClient.select() return dict shape
        wired_app.motor_mock.select.return_value = {
            "arm": {
                "id": arm["id"],
                "name": arm["name"],
                "index": arm["index"],
            },
            "policy": "RandomPolicy",
        }

        wired_app.selection_spy.events.clear()
        wired_app.feedback_spy.events.clear()

        resp = await client.post(
            "/api/v1/agent/select",
            json={
                "experiment_id": exp_id,
                "context": {
                    "id": "ctx-001",
                    "vector": None,
                    "metadata": {},
                },
            },
        )
        await wired_app.events.drain()

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["is_default"] is False
        assert data["request_id"], "expected a non-empty signed token"

        # motor was called once
        wired_app.motor_mock.select.assert_awaited_once()
        call_kwargs = wired_app.motor_mock.select.await_args.kwargs
        assert call_kwargs["tenant_id"] == "dev-tenant"
        assert call_kwargs["experiment_id"] == exp_id
        assert call_kwargs["context_id"] == "ctx-001"

        # one SelectionEvent published with the correct arm
        assert len(wired_app.selection_spy.events) == 1
        sel_event = wired_app.selection_spy.events[0]
        assert isinstance(sel_event, SelectionEvent)
        assert sel_event.experiment_id == exp_id
        assert sel_event.arm_id == arm["id"]
        assert sel_event.arm_index == arm["index"]
        assert sel_event.is_default is False
        assert sel_event.request_id == data["request_id"]

        # no feedback event on select
        assert len(wired_app.feedback_spy.events) == 0


# ── scenario 2 ────────────────────────────────────────────────────────────────


class TestSelectGateHit:
    async def test_select_gate_hit_skips_motor_and_publishes_gate_policy(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: when a feature gate evaluates to a committed arm, motorsvc is
        bypassed entirely.  the response has is_default=True and the published
        SelectionEvent.policy == "gate".

        gate setup: FeatureGateConfig with a rule that matches user_group=="beta".
        we call gate_svc.set_config directly so the two-level cache is primed
        before the select call.
        """
        pool_id, arms = await _create_pool(client, name="gate-hit-pool")
        exp_data = await _create_experiment(client, pool_id, name="gate-hit-exp")
        exp_id = exp_data["id"]
        committed_arm = arms[0]

        gate_config = FeatureGateConfig(
            experiment=ExperimentConfig(
                experiment_id=exp_id,
                enabled=True,
                arm=ArmConfig(
                    committed=BaseArmModel(
                        id=committed_arm["id"],
                        name=committed_arm["name"],
                        index=committed_arm["index"],
                    )
                ),
            ),
            rules=[
                Rule(
                    key="user_group",
                    operator="equals",
                    value="beta",
                    arm=ArmConfig(
                        committed=BaseArmModel(
                            id=committed_arm["id"],
                            name=committed_arm["name"],
                            index=committed_arm["index"],
                        )
                    ),
                )
            ],
        )
        await wired_app.gate_svc.set_config("dev-tenant", exp_id, gate_config)

        wired_app.motor_mock.select.reset_mock()
        wired_app.selection_spy.events.clear()

        resp = await client.post(
            "/api/v1/agent/select",
            json={
                "experiment_id": exp_id,
                "context": {
                    "id": "ctx-gate",
                    "vector": None,
                    "metadata": {"user_group": "beta"},
                },
            },
        )
        await wired_app.events.drain()

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["is_default"] is True

        # motor must NOT have been called
        wired_app.motor_mock.select.assert_not_awaited()

        # selection event published with policy="gate"
        assert len(wired_app.selection_spy.events) == 1
        sel_event = wired_app.selection_spy.events[0]
        assert isinstance(sel_event, SelectionEvent)
        assert sel_event.policy == "gate"
        assert sel_event.is_default is True
        assert sel_event.arm_id == committed_arm["id"]
        assert sel_event.experiment_id == exp_id


# ── scenario 3 ────────────────────────────────────────────────────────────────


class TestSelectMetaBandit:
    async def test_select_meta_bandit_publishes_event_under_learner_id(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: for a meta-bandit experiment, the published SelectionEvent uses
        the learner experiment id as experiment_id, not the parent experiment id.
        this is required so insights queries (which join on learner ids) find the data.

        motor is configured to return a response with learner_experiment_id set
        (matching MotorClient.select() return dict shape at client.py lines 99-101).
        """
        pool_id, arms = await _create_pool(client, name="meta-bandit-pool")

        # create meta experiment via the HTTP API (policy="auto", binary)
        meta_resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "meta-exp",
                "pool_id": pool_id,
                "policy": "auto",
                "policy_params": {"reward_type": "binary"},
                "enabled": True,
            },
        )
        assert meta_resp.status_code == 201, meta_resp.text
        meta_data = meta_resp.json()
        parent_id = meta_data["id"]
        learner_ids: list[str] = meta_data["policy_params"]["learners"]
        assert learner_ids, "expected at least one learner"
        learner_id = learner_ids[0]
        arm = arms[0]

        # motor returns a meta-bandit response: learner_experiment_id + learner_index
        # matching MotorClient.select() response parsing at client.py lines 99-101
        wired_app.motor_mock.select.return_value = {
            "arm": {
                "id": arm["id"],
                "name": arm["name"],
                "index": arm["index"],
            },
            "learner_experiment_id": learner_id,
            "learner_index": 0,
            "policy": "LinTSPolicy",
        }

        wired_app.selection_spy.events.clear()

        resp = await client.post(
            "/api/v1/agent/select",
            json={
                "experiment_id": parent_id,
                "context": {
                    "id": "ctx-meta",
                    "vector": None,
                    "metadata": {},
                },
            },
        )
        await wired_app.events.drain()

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["is_default"] is False
        # AgentSelectResponse strips internal meta-bandit fields from the body;
        # the learner context is carried inside the signed request_id token
        assert set(body) == {"arm", "request_id", "is_default"}
        assert "learner_experiment_id" not in body
        assert "learner_index" not in body

        # selection event experiment_id must be the learner, not the parent
        assert len(wired_app.selection_spy.events) == 1
        sel_event = wired_app.selection_spy.events[0]
        assert isinstance(sel_event, SelectionEvent)
        assert sel_event.experiment_id == learner_id, (
            f"expected learner id {learner_id!r}, got {sel_event.experiment_id!r}. "
            "insights queries join on learner ids so this must not be the parent."
        )
        assert sel_event.experiment_id != parent_id
        # policy carried straight from the motor response is the learner's
        assert sel_event.policy == "LinTSPolicy"


# ── scenario 4 ────────────────────────────────────────────────────────────────


class TestFeedbackValidToken:
    async def test_feedback_with_valid_token_publishes_feedback_event(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: POST /agent/feedback with the request_id from a prior select call
        publishes a FeedbackEvent whose arm_index matches the arm returned by motor.
        the response is 201 with accepted=True.
        """
        pool_id, arms = await _create_pool(client, name="feedback-valid-pool")
        exp_data = await _create_experiment(client, pool_id, name="feedback-valid-exp")
        exp_id = exp_data["id"]
        arm = arms[1]  # use variant (index=1) to verify index propagation

        wired_app.motor_mock.select.return_value = {
            "arm": {
                "id": arm["id"],
                "name": arm["name"],
                "index": arm["index"],
            },
            "policy": "RandomPolicy",
        }

        # perform the select to get a valid signed token
        select_resp = await client.post(
            "/api/v1/agent/select",
            json={
                "experiment_id": exp_id,
                "context": {
                    "id": "ctx-fb",
                    "vector": None,
                    "metadata": {},
                },
            },
        )
        await wired_app.events.drain()
        assert select_resp.status_code == 200, select_resp.text
        request_id = select_resp.json()["request_id"]

        wired_app.feedback_spy.events.clear()

        # submit feedback with the captured token
        fb_resp = await client.post(
            "/api/v1/agent/feedback",
            json={
                "request_id": request_id,
                "reward": 1.0,
            },
        )
        await wired_app.events.drain()

        assert fb_resp.status_code == 201, fb_resp.text
        assert fb_resp.json().get("accepted") is True

        # one FeedbackEvent published with the correct arm_index
        assert len(wired_app.feedback_spy.events) == 1
        fb_event = wired_app.feedback_spy.events[0]
        assert isinstance(fb_event, FeedbackEvent)
        assert fb_event.arm_index == arm["index"]
        assert fb_event.experiment_id == exp_id
        assert fb_event.request_id == request_id
        assert fb_event.reward == 1.0


# ── scenario 5 ────────────────────────────────────────────────────────────────


class TestFeedbackTamperedToken:
    async def test_feedback_with_tampered_token_returns_4xx_and_no_event(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: a tampered request_id fails HMAC verification inside
        SelectionToken.decode → TokenInvalidError → feed() raises TokenInvalidError
        → the router catches it as a generic exception and raises FeedbackException
        → HTTP 400.  no FeedbackEvent is published.
        """
        pool_id, arms = await _create_pool(client, name="tampered-token-pool")
        exp_data = await _create_experiment(client, pool_id, name="tampered-token-exp")
        exp_id = exp_data["id"]
        arm = arms[0]

        wired_app.motor_mock.select.return_value = {
            "arm": {
                "id": arm["id"],
                "name": arm["name"],
                "index": arm["index"],
            },
            "policy": "RandomPolicy",
        }

        # perform select to get a valid token
        select_resp = await client.post(
            "/api/v1/agent/select",
            json={
                "experiment_id": exp_id,
                "context": {
                    "id": "ctx-tamper",
                    "vector": None,
                    "metadata": {},
                },
            },
        )
        await wired_app.events.drain()
        assert select_resp.status_code == 200, select_resp.text
        valid_token = select_resp.json()["request_id"]

        # corrupt the signature: flip the last character of the base64 token.
        # the token format is base64url(json_payload + 16-byte HMAC).
        # flipping a character in the trailing region corrupts the HMAC.
        last_char = valid_token[-1]
        replacement = "A" if last_char != "A" else "B"
        tampered_token = valid_token[:-1] + replacement

        wired_app.feedback_spy.events.clear()

        fb_resp = await client.post(
            "/api/v1/agent/feedback",
            json={
                "request_id": tampered_token,
                "reward": 1.0,
            },
        )

        # FeedbackException extends BadRequestException → 400
        assert (
            fb_resp.status_code == 400
        ), f"expected 400 for tampered token, got {fb_resp.status_code}: {fb_resp.text}"

        # no feedback event should have been published
        assert len(wired_app.feedback_spy.events) == 0


# ── scenario 6 ────────────────────────────────────────────────────────────────


class TestSelectPausedExperiment:
    async def test_paused_experiment_serves_control_arm_without_token(
        self, client, wired_app, app_with_db
    ):
        """
        invariant: POST /agent/select on a paused (enabled=false) experiment
        returns 200 with is_default=true, the control arm (pool arm 0 when no
        gate default is set), and a null request_id — motor is never called.
        feeding the null token back is a no-op, not an error.
        """
        pool_id, arms = await _create_pool(client, name="paused-pool")
        exp_data = await _create_experiment(client, pool_id, name="paused-exp")
        exp_id = exp_data["id"]

        # pause it — re-syncs the redis record with enabled=false
        pause_resp = await client.patch(
            f"/api/v1/experiments/{exp_id}",
            json={"enabled": False},
        )
        assert pause_resp.status_code == 200, pause_resp.text

        wired_app.selection_spy.events.clear()
        wired_app.motor_mock.select.reset_mock()

        resp = await client.post(
            "/api/v1/agent/select",
            json={
                "experiment_id": exp_id,
                "context": {"id": "ctx-paused", "vector": None, "metadata": {}},
            },
        )
        await wired_app.events.drain()

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["is_default"] is True
        assert data["request_id"] is None
        assert data["arm"]["index"] == arms[0]["index"]

        # paused experiments never route to motor
        wired_app.motor_mock.select.assert_not_awaited()

        # feeding the null token back must not error
        fb_resp = await client.post(
            "/api/v1/agent/feedback",
            json={"request_id": "", "reward": 1.0},
        )
        await wired_app.events.drain()
        assert fb_resp.status_code == 201, fb_resp.text
        assert fb_resp.json()["accepted"] is False
        assert len(wired_app.feedback_spy.events) == 0


# ── scenario 6 ────────────────────────────────────────────────────────────────


class TestSelectContextVectorWidth:
    """a wrong-width or absent vector is a 400, not a 500.

    the whole point of the fix is that the request never reaches motor and is
    never metered, so every case here asserts motor was not called.
    """

    async def _contextual_experiment(self, client, *, name: str, dim: int = 4) -> str:
        pool_id, _ = await _create_pool(client, name=f"{name}-pool")
        exp = await _create_experiment(
            client,
            pool_id,
            name=name,
            policy="LinUCBPolicy",
            policy_params={"alpha": 1.0, "dim": dim},
        )
        return exp["id"]

    async def _select(self, client, exp_id: str, vector):
        return await client.post(
            "/api/v1/agent/select",
            json={
                "experiment_id": exp_id,
                "context": {"id": "ctx-w", "vector": vector, "metadata": {}},
            },
        )

    async def test_correct_width_reaches_motor(self, client, wired_app, app_with_db):
        exp_id = await self._contextual_experiment(client, name="ctx-ok")
        wired_app.motor_mock.select.return_value = {
            "arm": {"id": "a-0", "name": "control", "index": 0},
            "policy": "LinUCBPolicy",
        }

        resp = await self._select(client, exp_id, [0.1, 0.2, 0.3, 0.4])

        assert resp.status_code == 200, resp.text
        wired_app.motor_mock.select.assert_awaited_once()

    @pytest.mark.parametrize(
        "vector,width",
        [
            ([0.1, 0.2, 0.3], 3),
            ([0.1, 0.2, 0.3, 0.4, 0.5], 5),
            ([], 0),
            (None, 0),
        ],
    )
    async def test_wrong_width_is_400_and_never_reaches_motor(
        self, client, wired_app, app_with_db, vector, width
    ):
        exp_id = await self._contextual_experiment(
            client, name=f"ctx-bad-{width}-{len(vector or [])}"
        )
        wired_app.motor_mock.select.reset_mock()
        wired_app.selection_spy.events.clear()

        resp = await self._select(client, exp_id, vector)
        await wired_app.events.drain()

        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert body["code"] == "INVALID_CONTEXT_VECTOR"
        assert body["detail"] == (
            f"context.vector has width {width}, experiment expects 4"
        )

        wired_app.motor_mock.select.assert_not_awaited()
        assert len(wired_app.selection_spy.events) == 0

    async def test_paused_experiment_rejects_the_same_way(
        self, client, wired_app, app_with_db
    ):
        """pausing must not change what is accepted, or resuming becomes a cliff."""
        exp_id = await self._contextual_experiment(client, name="ctx-paused")
        pause = await client.patch(
            f"/api/v1/experiments/{exp_id}", json={"enabled": False}
        )
        assert pause.status_code == 200, pause.text

        resp = await self._select(client, exp_id, [0.1, 0.2])

        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "INVALID_CONTEXT_VECTOR"

    async def test_non_contextual_experiment_ignores_the_vector(
        self, client, wired_app, app_with_db
    ):
        pool_id, arms = await _create_pool(client, name="ctx-free-pool")
        exp = await _create_experiment(client, pool_id, name="ctx-free")
        wired_app.motor_mock.select.return_value = {
            "arm": {"id": arms[0]["id"], "name": arms[0]["name"], "index": 0},
            "policy": "RandomPolicy",
        }

        resp = await self._select(client, exp["id"], [0.1, 0.2, 0.3, 0.4, 0.5, 0.6])

        assert resp.status_code == 200, resp.text
        wired_app.motor_mock.select.assert_awaited_once()


# ── scenario 8 ────────────────────────────────────────────────────────────────


SCHEMA = [
    {"name": "device", "type": "categorical", "values": ["mobile", "desktop"]},
    {"name": "price", "type": "numeric", "min": 0, "max": 200},
]
# intercept + device(2 + other) + price = 5
ENCODED_DESKTOP_100 = [1.0, 0.0, 1.0, 0.0, 0.5]
ENCODED_DEFAULT = [1.0, 0.0, 0.0, 1.0, 0.5]


class TestSelectContextProperties:
    """the caller sends named properties, qbrix owns the encoding.

    the encoded vector is minted into the token, so feedback replays it and
    nothing downstream re-encodes — that round trip is the invariant the whole
    project rests on.
    """

    async def _schema_experiment(self, client, *, name: str) -> str:
        pool_id, _ = await _create_pool(client, name=f"{name}-pool")
        exp = await _create_experiment(
            client,
            pool_id,
            name=name,
            policy="LinUCBPolicy",
            policy_params={"alpha": 1.0, "context_schema": SCHEMA},
        )
        assert exp["policy_params"]["dim"] == 5
        return exp["id"]

    async def _select(self, client, exp_id: str, context: dict):
        return await client.post(
            "/api/v1/agent/select",
            json={"experiment_id": exp_id, "context": {"id": "ctx-p", **context}},
        )

    async def test_properties_are_encoded_before_motor_sees_them(
        self, client, wired_app, app_with_db
    ):
        """motor is handed a vector; it never learns properties exist."""
        exp_id = await self._schema_experiment(client, name="ctx-props")
        wired_app.motor_mock.select.return_value = {
            "arm": {"id": "a-0", "name": "control", "index": 0},
            "policy": "LinUCBPolicy",
        }

        resp = await self._select(
            client, exp_id, {"properties": {"device": "desktop", "price": 100}}
        )

        assert resp.status_code == 200, resp.text
        wired_app.motor_mock.select.assert_awaited_once()
        assert (
            wired_app.motor_mock.select.await_args.kwargs["context_vector"]
            == ENCODED_DESKTOP_100
        )

    async def test_encoded_vector_round_trips_through_the_token_to_feedback(
        self, client, wired_app, app_with_db
    ):
        """encode once at select; feedback trains on that exact vector."""
        exp_id = await self._schema_experiment(client, name="ctx-roundtrip")
        wired_app.motor_mock.select.return_value = {
            "arm": {"id": "a-0", "name": "control", "index": 0},
            "policy": "LinUCBPolicy",
        }

        select_resp = await self._select(
            client, exp_id, {"properties": {"device": "desktop", "price": 100}}
        )
        assert select_resp.status_code == 200, select_resp.text
        request_id = select_resp.json()["request_id"]

        await wired_app.events.drain()
        wired_app.feedback_spy.events.clear()

        fb_resp = await client.post(
            "/api/v1/agent/feedback",
            json={"request_id": request_id, "reward": 1.0},
        )
        await wired_app.events.drain()

        assert fb_resp.status_code == 201, fb_resp.text
        assert len(wired_app.feedback_spy.events) == 1
        assert wired_app.feedback_spy.events[0].context_vector == ENCODED_DESKTOP_100

    async def test_no_properties_serves_the_default_vector(
        self, client, wired_app, app_with_db
    ):
        """a schema gives an absent context a real point to sit at."""
        exp_id = await self._schema_experiment(client, name="ctx-default")
        wired_app.motor_mock.select.return_value = {
            "arm": {"id": "a-0", "name": "control", "index": 0},
            "policy": "LinUCBPolicy",
        }

        resp = await self._select(client, exp_id, {"metadata": {}})

        assert resp.status_code == 200, resp.text
        assert (
            wired_app.motor_mock.select.await_args.kwargs["context_vector"]
            == ENCODED_DEFAULT
        )

    async def test_bad_property_type_is_400_and_never_reaches_motor(
        self, client, wired_app, app_with_db
    ):
        exp_id = await self._schema_experiment(client, name="ctx-badtype")
        wired_app.motor_mock.select.reset_mock()

        resp = await self._select(client, exp_id, {"properties": {"price": "lots"}})

        assert resp.status_code == 400
        assert "price" in resp.text
        wired_app.motor_mock.select.assert_not_awaited()

    async def test_vector_against_a_schema_experiment_is_400(
        self, client, wired_app, app_with_db
    ):
        exp_id = await self._schema_experiment(client, name="ctx-wrongchannel")
        wired_app.motor_mock.select.reset_mock()

        resp = await self._select(client, exp_id, {"vector": [1.0, 0.0, 1.0, 0.0, 0.5]})

        assert resp.status_code == 400
        assert "context.properties" in resp.text
        wired_app.motor_mock.select.assert_not_awaited()

    async def test_both_channels_together_is_400(self, client, wired_app, app_with_db):
        exp_id = await self._schema_experiment(client, name="ctx-both")
        wired_app.motor_mock.select.reset_mock()

        resp = await self._select(
            client,
            exp_id,
            {"vector": [1.0, 0.0, 1.0, 0.0, 0.5], "properties": {"device": "mobile"}},
        )

        assert resp.status_code == 400
        assert "not both" in resp.text
        wired_app.motor_mock.select.assert_not_awaited()

    async def test_properties_against_a_vector_experiment_is_400(
        self, client, wired_app, app_with_db
    ):
        """the dim-only escape hatch does not accept properties."""
        pool_id, _ = await _create_pool(client, name="ctx-dimonly-pool")
        exp = await _create_experiment(
            client,
            pool_id,
            name="ctx-dimonly",
            policy="LinUCBPolicy",
            policy_params={"alpha": 1.0, "dim": 4},
        )
        wired_app.motor_mock.select.reset_mock()

        resp = await self._select(
            client, exp["id"], {"properties": {"device": "mobile"}}
        )

        assert resp.status_code == 400
        assert "not created with a context schema" in resp.text
        wired_app.motor_mock.select.assert_not_awaited()

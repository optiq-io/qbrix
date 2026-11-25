"""the state that ties github's round trip to one workspace and admin is
signed, lives fifteen minutes and is good for one step only."""

from __future__ import annotations

import base64
import json

import pytest

from proxysvc.core.error import GitHubStateError
from proxysvc.mod.github.state import TTL_SEC
from proxysvc.mod.github.state import State
from proxysvc.mod.github.state import StateSigner

pytestmark = pytest.mark.unit

NOW = 1_800_000_000.0
STATE = State(tenant_id="t1", user_id="u1", step="created", events_token="tok")


@pytest.fixture
def signer() -> StateSigner:
    return StateSigner(b"k" * 32)


def test_round_trips(signer):
    token = signer.sign(STATE, now=NOW)

    assert signer.verify(token, step="created", now=NOW + TTL_SEC) == STATE


def test_expires(signer):
    token = signer.sign(STATE, now=NOW)

    with pytest.raises(GitHubStateError, match="expired"):
        signer.verify(token, step="created", now=NOW + TTL_SEC + 1)


def test_is_good_for_its_own_step_only(signer):
    token = signer.sign(STATE, now=NOW)

    with pytest.raises(GitHubStateError, match="installed"):
        signer.verify(token, step="installed", now=NOW)


def test_another_key_is_refused(signer):
    token = StateSigner(b"x" * 32).sign(STATE, now=NOW)

    with pytest.raises(GitHubStateError, match="signed"):
        signer.verify(token, step="created", now=NOW)


def test_an_altered_tenant_is_refused(signer):
    raw = base64.urlsafe_b64decode(signer.sign(STATE, now=NOW))
    payload, sig = json.loads(raw[:-16]), raw[-16:]
    payload["tid"] = "t2"
    forged = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode() + sig
    ).decode()

    with pytest.raises(GitHubStateError):
        signer.verify(forged, step="created", now=NOW)


@pytest.mark.parametrize("token", ["", "not-a-state", "AAAA"])
def test_garbage_is_refused(signer, token):
    with pytest.raises(GitHubStateError):
        signer.verify(token, step="created", now=NOW)

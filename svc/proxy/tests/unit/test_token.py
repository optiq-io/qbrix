"""unit tests for SelectionToken encode/decode."""

from __future__ import annotations

import base64
import time
from unittest.mock import patch

import pytest

from proxysvc.mod.agent.token import (
    SelectionToken,
    SelectionEntry,
)
from proxysvc.core.error import TokenExpiredError, TokenInvalidError


class TestSelectionTokenEncodeDecode:

    def test_roundtrip_preserves_all_fields(self, token_secret):
        token = SelectionToken.encode(
            secret=token_secret,
            tenant_id="t-1",
            experiment_id="exp-1",
            arm_index=2,
            context_id="ctx-abc",
            context_vector=[1.0, 2.5, 3.0],
            context_metadata={"region": "us", "device": "mobile"},
        )
        entry = SelectionToken.decode(secret=token_secret, token=token, tenant_id="t-1")

        assert isinstance(entry, SelectionEntry)
        assert entry.tenant_id == "t-1"
        assert entry.experiment_id == "exp-1"
        assert entry.arm_index == 2
        assert entry.context_id == "ctx-abc"
        assert entry.context_vector == [1.0, 2.5, 3.0]
        assert entry.context_metadata == {"region": "us", "device": "mobile"}
        assert isinstance(entry.timestamp_ms, int)

    def test_empty_context(self, token_secret):
        token = SelectionToken.encode(
            secret=token_secret,
            tenant_id="t-1",
            experiment_id="exp-1",
            arm_index=0,
            context_id="",
            context_vector=[],
            context_metadata={},
        )
        entry = SelectionToken.decode(secret=token_secret, token=token, tenant_id="t-1")

        assert entry.context_id == ""
        assert entry.context_vector == []
        assert entry.context_metadata == {}


class TestSelectionTokenExpiry:

    def test_expired_token_raises(self, token_secret):
        # encode the token with a timestamp 10 seconds in the past
        old_time = time.time() - 10
        with patch("proxysvc.mod.agent.token.time.time", return_value=old_time):
            token = SelectionToken.encode(
                secret=token_secret,
                tenant_id="t-1",
                experiment_id="exp-1",
                arm_index=0,
                context_id="ctx-1",
                context_vector=[],
                context_metadata={},
            )
        # decode with max_age_ms=5000 (5s); token is 10s old → expired
        with pytest.raises(TokenExpiredError):
            SelectionToken.decode(
                secret=token_secret,
                token=token,
                tenant_id="t-1",
                max_age_ms=5000,
            )

    def test_no_max_age_skips_expiry(self, token_secret):
        token = SelectionToken.encode(
            secret=token_secret,
            tenant_id="t-1",
            experiment_id="exp-1",
            arm_index=0,
            context_id="ctx-1",
            context_vector=[],
            context_metadata={},
        )
        # should succeed regardless, no expiry check
        entry = SelectionToken.decode(
            secret=token_secret,
            token=token,
            tenant_id="t-1",
            max_age_ms=None,
        )
        assert entry.tenant_id == "t-1"


class TestSelectionTokenInvalid:

    def test_tampered_payload_raises(self, token_secret):
        token = SelectionToken.encode(
            secret=token_secret,
            tenant_id="t-1",
            experiment_id="exp-1",
            arm_index=0,
            context_id="ctx-1",
            context_vector=[],
            context_metadata={},
        )
        # tamper with the base64 payload
        raw = base64.urlsafe_b64decode(token)
        tampered = bytes([raw[0] ^ 0xFF]) + raw[1:]
        tampered_token = base64.urlsafe_b64encode(tampered).decode()

        with pytest.raises(TokenInvalidError):
            SelectionToken.decode(
                secret=token_secret, token=tampered_token, tenant_id="t-1"
            )

    def test_malformed_base64_raises(self, token_secret):
        with pytest.raises(TokenInvalidError):
            SelectionToken.decode(
                secret=token_secret, token="not-valid-base64!!!", tenant_id="t-1"
            )

    def test_token_too_short_raises(self, token_secret):
        short_data = base64.urlsafe_b64encode(b"short").decode()
        with pytest.raises(TokenInvalidError, match="token too short"):
            SelectionToken.decode(
                secret=token_secret, token=short_data, tenant_id="t-1"
            )

    def test_wrong_secret_raises(self, token_secret):
        token = SelectionToken.encode(
            secret=token_secret,
            tenant_id="t-1",
            experiment_id="exp-1",
            arm_index=0,
            context_id="ctx-1",
            context_vector=[],
            context_metadata={},
        )
        wrong_secret = b"completely-different-secret"
        with pytest.raises(TokenInvalidError, match="invalid token signature"):
            SelectionToken.decode(secret=wrong_secret, token=token, tenant_id="t-1")


class TestSelectionTokenTenant:

    @staticmethod
    def _token(token_secret, **kwargs) -> str:
        return SelectionToken.encode(
            secret=token_secret,
            tenant_id="t-1",
            experiment_id="exp-1",
            arm_index=0,
            context_id="ctx-1",
            context_vector=[],
            context_metadata={},
            **kwargs,
        )

    def test_a_token_issued_to_another_tenant_is_invalid(self, token_secret):
        token = self._token(token_secret)

        with pytest.raises(TokenInvalidError, match="not issued to this workspace"):
            SelectionToken.decode(secret=token_secret, token=token, tenant_id="t-2")

    def test_the_tenant_is_checked_before_the_age(self, token_secret):
        with patch("proxysvc.mod.agent.token.time.time", return_value=time.time() - 10):
            token = self._token(token_secret)

        with pytest.raises(TokenInvalidError):
            SelectionToken.decode(
                secret=token_secret, token=token, tenant_id="t-2", max_age_ms=5000
            )

    def test_a_meta_token_decodes_for_its_own_tenant(self, token_secret):
        token = self._token(
            token_secret,
            meta_experiment_id="meta-1",
            learner_index=1,
            learner_experiment_id="exp-1",
        )

        entry = SelectionToken.decode(secret=token_secret, token=token, tenant_id="t-1")

        assert entry.meta_experiment_id == "meta-1"
        assert entry.learner_index == 1

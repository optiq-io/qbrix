from __future__ import annotations

import pytest
from pydantic import ValidationError

from proxysvc.config import ProxySettings


class TestConnectionLimits:

    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("PROXY_MCP_CALLS_PER_MINUTE", raising=False)
        monkeypatch.delenv("PROXY_MCP_CHANGES_PER_MINUTE", raising=False)

        settings = ProxySettings()

        assert settings.mcp_calls_per_minute == 120
        assert settings.mcp_changes_per_minute == 30

    def test_read_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("PROXY_MCP_CALLS_PER_MINUTE", "600")
        monkeypatch.setenv("PROXY_MCP_CHANGES_PER_MINUTE", "100")

        settings = ProxySettings()

        assert settings.mcp_calls_per_minute == 600
        assert settings.mcp_changes_per_minute == 100

    @pytest.mark.parametrize(
        "variable", ["PROXY_MCP_CALLS_PER_MINUTE", "PROXY_MCP_CHANGES_PER_MINUTE"]
    )
    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_a_limit_below_one_fails_at_boot(self, monkeypatch, variable, value):
        monkeypatch.setenv(variable, value)

        with pytest.raises(ValidationError):
            ProxySettings()


class TestDerivedKey:

    def test_a_label_always_derives_the_same_key(self):
        settings = ProxySettings(secret_box_key="k" * 64)

        assert settings.derived_key("mcp-request-state") == ProxySettings(
            secret_box_key="k" * 64
        ).derived_key("mcp-request-state")
        assert len(settings.derived_key("mcp-request-state")) == 32

    def test_each_label_and_root_derives_its_own(self):
        settings = ProxySettings(secret_box_key="k" * 64)

        assert settings.derived_key("mcp-request-state") != settings.derived_key(
            "secret-box"
        )
        assert settings.derived_key("mcp-request-state") != ProxySettings(
            secret_box_key="j" * 64
        ).derived_key("mcp-request-state")

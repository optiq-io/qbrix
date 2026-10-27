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

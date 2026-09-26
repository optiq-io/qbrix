import json
import logging
import os
from io import StringIO

import pytest

from qbrixlog import configure_logging
from qbrixlog import get_logger
from qbrixlog import request_context
from qbrixlog import get_request_id
from qbrixlog import set_request_id
from qbrixlog.config import _configured_services


@pytest.fixture(autouse=True)
def reset_logging():
    """reset logging state between tests."""
    _configured_services.clear()
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    yield


class TestConfigureLogging:
    def test_configure_logging_sets_level(self):
        configure_logging("test", level="DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_configure_logging_uses_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_LOG_LEVEL", "WARNING")
        configure_logging("test")
        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_configure_logging_only_once(self):
        configure_logging("test", level="INFO")
        configure_logging("test", level="DEBUG")
        root = logging.getLogger()
        assert root.level == logging.INFO


class TestGetLogger:
    def test_get_logger_returns_logger(self):
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"


class TestRequestContext:
    def test_request_context_sets_id(self):
        assert get_request_id() is None
        with request_context("req-123"):
            assert get_request_id() == "req-123"
        assert get_request_id() is None

    def test_request_context_generates_id(self):
        with request_context() as req_id:
            assert req_id is not None
            assert len(req_id) == 32

    def test_set_request_id(self):
        set_request_id("manual-id")
        assert get_request_id() == "manual-id"
        set_request_id(None)
        assert get_request_id() is None


class TestJSONFormatter:
    def test_json_format_output(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT", "json")

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        configure_logging("testservice")

        root = logging.getLogger()
        root.handlers = [handler]

        from qbrixlog.formatters import JSONFormatter

        handler.setFormatter(JSONFormatter("testservice"))

        logger = get_logger("test.json")
        with request_context("req-abc"):
            logger.info("test message")

        output = stream.getvalue()
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["service"] == "testservice"
        assert data["logger"] == "test.json"
        assert data["message"] == "test message"
        assert data["request_id"] == "req-abc"
        assert "timestamp" in data


class TestTextFormatter:
    def test_text_format_output(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)

        from qbrixlog.formatters import TextFormatter

        handler.setFormatter(TextFormatter("testservice"))
        handler.setLevel(logging.INFO)

        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.handlers = [handler]

        logger = get_logger("test.text")
        logger.info("hello world")

        output = stream.getvalue()
        assert "[INFO" in output
        assert "[testservice]" in output
        assert "test.text" in output
        assert "hello world" in output


class TestSentry:
    @pytest.fixture
    def captured_init(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "qbrixlog.config.sentry_sdk.init", lambda **kw: calls.append(kw)
        )
        return calls

    def test_init_disabled_without_dsn(self, captured_init):
        configure_logging("sentrytest")
        assert captured_init[0]["dsn"] is None

    def test_init_uses_service_specific_dsn(self, monkeypatch, captured_init):
        monkeypatch.setenv(
            "SENTRYTEST_SENTRY_DSN", "https://svc@example.ingest.sentry.io/1"
        )
        monkeypatch.setenv("SENTRY_DSN", "https://global@example.ingest.sentry.io/2")
        configure_logging("sentrytest")
        assert captured_init[0]["dsn"] == "https://svc@example.ingest.sentry.io/1"

    def test_init_falls_back_to_global_dsn(self, monkeypatch, captured_init):
        monkeypatch.setenv("SENTRY_DSN", "https://global@example.ingest.sentry.io/2")
        configure_logging("sentrytest")
        assert captured_init[0]["dsn"] == "https://global@example.ingest.sentry.io/2"

    def test_init_reads_environment_and_release(self, monkeypatch, captured_init):
        monkeypatch.setenv("SENTRY_ENVIRONMENT", "prod")
        monkeypatch.setenv("SENTRY_RELEASE", "abc123")
        configure_logging("sentrytest")
        assert captured_init[0]["environment"] == "prod"
        assert captured_init[0]["release"] == "abc123"

    def test_init_never_traces_or_sends_pii(self, monkeypatch, captured_init):
        monkeypatch.setenv("SENTRY_DSN", "https://global@example.ingest.sentry.io/2")
        configure_logging("sentrytest")
        assert captured_init[0]["traces_sample_rate"] == 0.0
        assert captured_init[0]["send_default_pii"] is False

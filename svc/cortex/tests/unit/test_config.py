import os
import pytest

from cortexsvc.config import CortexSettings


class TestCortexSettingsDefaults:
    """test default configuration values."""

    def test_default_grpc_host(self):
        # arrange & act
        settings = CortexSettings()

        # assert
        assert settings.grpc_host == "0.0.0.0"

    def test_default_grpc_port(self):
        # arrange & act
        settings = CortexSettings()

        # assert
        assert settings.grpc_port == 50052

    def test_default_redis_host(self):
        # arrange & act
        settings = CortexSettings()

        # assert
        assert settings.redis_host == "localhost"

    def test_default_redis_port(self):
        # arrange & act
        settings = CortexSettings()

        # assert
        assert settings.redis_port == 6379

    def test_default_redis_password(self):
        # arrange & act
        settings = CortexSettings()

        # assert
        assert settings.redis_password is None

    def test_default_redis_db(self):
        # arrange & act
        settings = CortexSettings()

        # assert
        assert settings.redis_db == 0

    def test_default_stream_name(self):
        # arrange & act
        settings = CortexSettings()

        # assert
        assert settings.stream_name == "qbrix:feedback"

    def test_default_consumer_group(self):
        # arrange & act
        settings = CortexSettings()

        # assert
        assert settings.consumer_group == "cortex"

    def test_default_consumer_name(self):
        # arrange & act
        settings = CortexSettings()

        # assert
        assert settings.consumer_name == "worker-0"

    def test_default_batch_size(self):
        # arrange & act
        settings = CortexSettings()

        # assert
        assert settings.batch_size == 256

    def test_default_batch_timeout_ms(self):
        # arrange & act
        settings = CortexSettings()

        # assert
        assert settings.batch_timeout_ms == 100

    def test_default_flush_interval_sec(self):
        # arrange & act
        settings = CortexSettings()

        # assert
        assert settings.flush_interval_sec == 10


class TestCortexSettingsCustomization:
    """test custom configuration values."""

    def test_custom_grpc_settings(self):
        # arrange & act
        settings = CortexSettings(
            grpc_host="127.0.0.1",
            grpc_port=8080
        )

        # assert
        assert settings.grpc_host == "127.0.0.1"
        assert settings.grpc_port == 8080

    def test_custom_redis_settings(self):
        # arrange & act
        settings = CortexSettings(
            redis_host="redis.example.com",
            redis_port=6380,
            redis_password="secret123",
            redis_db=1
        )

        # assert
        assert settings.redis_host == "redis.example.com"
        assert settings.redis_port == 6380
        assert settings.redis_password == "secret123"
        assert settings.redis_db == 1

    def test_custom_stream_settings(self):
        # arrange & act
        settings = CortexSettings(
            stream_name="custom:stream",
            consumer_group="custom-group",
            consumer_name="worker-5"
        )

        # assert
        assert settings.stream_name == "custom:stream"
        assert settings.consumer_group == "custom-group"
        assert settings.consumer_name == "worker-5"

    def test_custom_batch_settings(self):
        # arrange & act
        settings = CortexSettings(
            batch_size=512,
            batch_timeout_ms=500,
            flush_interval_sec=30
        )

        # assert
        assert settings.batch_size == 512
        assert settings.batch_timeout_ms == 500
        assert settings.flush_interval_sec == 30


class TestCortexSettingsRedisUrl:
    """test redis url construction."""

    def test_redis_url_without_password(self):
        # arrange
        settings = CortexSettings(
            redis_host="localhost",
            redis_port=6379,
            redis_db=0
        )

        # act
        url = settings.redis_url

        # assert
        assert url == "redis://localhost:6379/0"

    def test_redis_url_with_password(self):
        # arrange
        settings = CortexSettings(
            redis_host="redis.example.com",
            redis_port=6380,
            redis_password="mypassword",
            redis_db=2
        )

        # act
        url = settings.redis_url

        # assert
        assert url == "redis://:mypassword@redis.example.com:6380/2"

    def test_redis_url_with_custom_db(self):
        # arrange
        settings = CortexSettings(
            redis_host="localhost",
            redis_port=6379,
            redis_db=5
        )

        # act
        url = settings.redis_url

        # assert
        assert url == "redis://localhost:6379/5"


class TestCortexSettingsEnvironmentVariables:
    """test loading from environment variables."""

    def test_load_grpc_host_from_env(self, monkeypatch):
        # arrange
        monkeypatch.setenv("CORTEX_GRPC_HOST", "192.168.1.1")

        # act
        settings = CortexSettings()

        # assert
        assert settings.grpc_host == "192.168.1.1"

    def test_load_grpc_port_from_env(self, monkeypatch):
        # arrange
        monkeypatch.setenv("CORTEX_GRPC_PORT", "9999")

        # act
        settings = CortexSettings()

        # assert
        assert settings.grpc_port == 9999

    def test_load_redis_settings_from_env(self, monkeypatch):
        # arrange
        monkeypatch.setenv("CORTEX_REDIS_HOST", "redis-prod")
        monkeypatch.setenv("CORTEX_REDIS_PORT", "6380")
        monkeypatch.setenv("CORTEX_REDIS_PASSWORD", "prod-secret")
        monkeypatch.setenv("CORTEX_REDIS_DB", "3")

        # act
        settings = CortexSettings()

        # assert
        assert settings.redis_host == "redis-prod"
        assert settings.redis_port == 6380
        assert settings.redis_password == "prod-secret"
        assert settings.redis_db == 3

    def test_load_stream_settings_from_env(self, monkeypatch):
        # arrange
        monkeypatch.setenv("CORTEX_STREAM_NAME", "prod:feedback")
        monkeypatch.setenv("CORTEX_CONSUMER_GROUP", "prod-cortex")
        monkeypatch.setenv("CORTEX_CONSUMER_NAME", "worker-prod-1")

        # act
        settings = CortexSettings()

        # assert
        assert settings.stream_name == "prod:feedback"
        assert settings.consumer_group == "prod-cortex"
        assert settings.consumer_name == "worker-prod-1"

    def test_load_batch_settings_from_env(self, monkeypatch):
        # arrange
        monkeypatch.setenv("CORTEX_BATCH_SIZE", "1024")
        monkeypatch.setenv("CORTEX_BATCH_TIMEOUT_MS", "200")
        monkeypatch.setenv("CORTEX_FLUSH_INTERVAL_SEC", "60")

        # act
        settings = CortexSettings()

        # assert
        assert settings.batch_size == 1024
        assert settings.batch_timeout_ms == 200
        assert settings.flush_interval_sec == 60

    def test_env_prefix_is_cortex(self, monkeypatch):
        # arrange
        # setting without CORTEX_ prefix should not be picked up
        monkeypatch.setenv("GRPC_PORT", "7777")
        # setting with CORTEX_ prefix should be picked up
        monkeypatch.setenv("CORTEX_GRPC_PORT", "8888")

        # act
        settings = CortexSettings()

        # assert
        assert settings.grpc_port == 8888

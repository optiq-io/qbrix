"""shared fixtures for proxysvc unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

# make sibling modules (e.g. factories) importable without __init__.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from unittest.mock import AsyncMock

from proxysvc.config import ProxySettings


@pytest.fixture
def proxy_settings() -> ProxySettings:
    return ProxySettings(
        runenv="test",
        postgres_host="localhost",
        postgres_port=5432,
        postgres_user="test",
        postgres_password="test",
        postgres_database="test",
        redis_host="localhost",
        redis_port=6379,
        token_secret="test-secret-key-for-unit-tests",
        jwt_secret_key="test-jwt-secret",
        jwt_algorithm="HS256",
        jwt_access_token_expire_minutes=30,
        jwt_refresh_token_expire_days=7,
        gate_cache_maxsize=100,
        gate_cache_ttl=10.0,
        gate_redis_ttl=60,
    )


@pytest.fixture
def token_secret() -> bytes:
    return b"test-secret-key-for-unit-tests"


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.client = AsyncMock()
    redis.client.ping = AsyncMock(return_value=True)
    redis.client.get = AsyncMock(return_value=None)
    redis.client.set = AsyncMock()
    redis.client.delete = AsyncMock(return_value=1)
    redis.client.xlen = AsyncMock(return_value=0)
    redis.get_experiment = AsyncMock(return_value=None)
    redis.set_experiment = AsyncMock()
    redis.delete_experiment = AsyncMock()
    redis.delete_params = AsyncMock()
    redis.get_gate_config = AsyncMock(return_value=None)
    redis.set_gate_config = AsyncMock()
    redis.delete_gate_config = AsyncMock()
    redis.connect = AsyncMock()
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def mock_feedback_publisher() -> AsyncMock:
    publisher = AsyncMock()
    publisher.publish = AsyncMock()
    publisher.connect = AsyncMock()
    publisher.close = AsyncMock()
    return publisher


@pytest.fixture
def mock_motor_client() -> AsyncMock:
    client = AsyncMock()
    client.select = AsyncMock(
        return_value={
            "arm": {"id": "arm-1", "name": "control", "index": 0},
        }
    )
    client.health = AsyncMock(return_value=True)
    client.connect = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_cortex_client() -> AsyncMock:
    client = AsyncMock()
    client.health = AsyncMock(return_value=True)
    client.connect = AsyncMock()
    client.close = AsyncMock()
    client.flush_batch = AsyncMock(return_value=0)
    return client

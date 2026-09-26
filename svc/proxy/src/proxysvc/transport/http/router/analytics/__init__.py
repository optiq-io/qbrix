from __future__ import annotations

from typing import Optional

from qbrixstore.clickhouse.client import ClickHouseClient
from qbrixstore.config import ClickHouseSettings

from proxysvc.config import settings

_clickhouse_client: Optional[ClickHouseClient] = None


def get_clickhouse_client() -> ClickHouseClient:
    """get or create the clickhouse client shared by the analytics endpoints."""
    global _clickhouse_client
    if _clickhouse_client is None:
        ch_settings = ClickHouseSettings(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            user=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
        )
        _clickhouse_client = ClickHouseClient(ch_settings)
        _clickhouse_client.connect()
    return _clickhouse_client

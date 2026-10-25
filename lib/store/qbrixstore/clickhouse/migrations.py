from __future__ import annotations

from clickhouse_connect.driver.client import Client

SELECTION_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS selection_events (
    tenant_id String,
    experiment_id String,
    request_id String,
    event_id String,
    arm_id String,
    arm_name String,
    arm_index UInt16,
    is_default Bool,
    context_id String,
    context_vector Array(Float64),
    context_metadata String,
    timestamp_ms Int64,
    policy String,
    loop_id String,
    cycle_id String,
    decision_id String,
    reason String,
    unit String,
    properties String,
    metric_id String,
    metric_version String,
    metric_type String,
    score_lo Float64,
    score_hi Float64,
    window_ms Int64,
    event_date Date DEFAULT toDate(fromUnixTimestamp64Milli(timestamp_ms))
)
ENGINE = MergeTree()
PARTITION BY (tenant_id, toYYYYMM(event_date))
ORDER BY (tenant_id, experiment_id, timestamp_ms, request_id)
TTL event_date + INTERVAL {ttl_days} DAY
SETTINGS index_granularity = 8192
"""

FEEDBACK_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS feedback_events (
    tenant_id String,
    experiment_id String,
    request_id String,
    arm_index UInt16,
    reward Float64,
    context_id String,
    context_vector Array(Float64),
    context_metadata String,
    timestamp_ms Int64,
    event_date Date DEFAULT toDate(fromUnixTimestamp64Milli(timestamp_ms))
)
ENGINE = MergeTree()
PARTITION BY (tenant_id, toYYYYMM(event_date))
ORDER BY (tenant_id, experiment_id, timestamp_ms, request_id)
TTL event_date + INTERVAL {ttl_days} DAY
SETTINGS index_granularity = 8192
"""

AUDIT_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS audit_events (
    name String,
    tenant_id String,
    actor_id String,
    resource_type String,
    resource_id String,
    payload String,
    timestamp_ms Int64,
    event_date Date DEFAULT toDate(fromUnixTimestamp64Milli(timestamp_ms))
)
ENGINE = MergeTree()
PARTITION BY (tenant_id, toYYYYMM(event_date))
ORDER BY (tenant_id, timestamp_ms, name)
TTL event_date + INTERVAL {ttl_days} DAY
SETTINGS index_granularity = 8192
"""

DROP_SELECTION_EVENTS = "DROP TABLE IF EXISTS selection_events"
DROP_FEEDBACK_EVENTS = "DROP TABLE IF EXISTS feedback_events"
DROP_AUDIT_EVENTS = "DROP TABLE IF EXISTS audit_events"

# idempotent column additions for tables created before the column existed;
# there is no versioned clickhouse migration runner, so we alter in place.
SELECTION_EVENTS_ALTERS = [
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS event_id String",
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS loop_id String",
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS cycle_id String",
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS decision_id String",
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS reason String",
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS unit String",
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS properties String",
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS metric_id String",
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS metric_version String",
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS metric_type String",
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS score_lo Float64",
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS score_hi Float64",
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS window_ms Int64",
]


def create_tables(client: Client, ttl_days: int = 90) -> None:
    """create clickhouse tables for event storage."""
    client.command(SELECTION_EVENTS_TABLE.format(ttl_days=ttl_days))
    client.command(FEEDBACK_EVENTS_TABLE.format(ttl_days=ttl_days))
    client.command(AUDIT_EVENTS_TABLE.format(ttl_days=ttl_days))
    for alter in SELECTION_EVENTS_ALTERS:
        client.command(alter)


def drop_tables(client: Client) -> None:
    """drop clickhouse tables."""
    client.command(DROP_SELECTION_EVENTS)
    client.command(DROP_FEEDBACK_EVENTS)
    client.command(DROP_AUDIT_EVENTS)


def create_database(client: Client, database: str) -> None:
    """create database if it doesn't exist."""
    client.command(f"CREATE DATABASE IF NOT EXISTS {database}")

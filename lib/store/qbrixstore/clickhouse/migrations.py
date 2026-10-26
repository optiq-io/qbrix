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
    ledger_ms Int64 DEFAULT timestamp_ms,
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

METRIC_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS metric_events (
    tenant_id String,
    metric_id String,
    metric_version String,
    value Float64,
    decisions Array(Tuple(decision_id String, loop_id String, cycle_id String, option_index UInt16, opened_ms Int64)),
    unit String,
    event_id String,
    at_ms Int64,
    received_ms Int64,
    source LowCardinality(String),
    ledger_ms Int64 DEFAULT received_ms,
    event_date Date DEFAULT toDate(fromUnixTimestamp64Milli(at_ms))
)
ENGINE = MergeTree()
PARTITION BY (tenant_id, toYYYYMM(event_date))
ORDER BY (tenant_id, at_ms, event_id)
TTL event_date + INTERVAL {ttl_days} DAY
SETTINGS index_granularity = 8192
"""

SEALED_DECISIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sealed_decisions (
    tenant_id String,
    loop_id String,
    cycle_id String,
    decision_id String,
    option_index UInt16,
    unit String,
    metric_id String,
    metric_version String,
    metric_type LowCardinality(String),
    opened_ms Int64,
    sealed_ms Int64,
    sealed_by LowCardinality(String),
    value Nullable(Float64),
    outcomes UInt32,
    opened_date Date DEFAULT toDate(fromUnixTimestamp64Milli(opened_ms))
)
ENGINE = ReplacingMergeTree()
PARTITION BY (tenant_id, toYYYYMM(opened_date))
ORDER BY (tenant_id, cycle_id, decision_id)
TTL opened_date + INTERVAL {ttl_days} DAY
SETTINGS index_granularity = 8192
"""

DROP_SELECTION_EVENTS = "DROP TABLE IF EXISTS selection_events"
DROP_FEEDBACK_EVENTS = "DROP TABLE IF EXISTS feedback_events"
DROP_AUDIT_EVENTS = "DROP TABLE IF EXISTS audit_events"
DROP_METRIC_EVENTS = "DROP TABLE IF EXISTS metric_events"
DROP_SEALED_DECISIONS = "DROP TABLE IF EXISTS sealed_decisions"

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
    "ALTER TABLE selection_events ADD COLUMN IF NOT EXISTS ledger_ms Int64 DEFAULT timestamp_ms",
]

METRIC_EVENTS_ALTERS = [
    "ALTER TABLE metric_events ADD COLUMN IF NOT EXISTS ledger_ms Int64 DEFAULT received_ms",
]

# the sealer reads decisions by when their window closes and outcomes by when
# they reached the ledger, neither of which leads the order key.
LEDGER_INDEXES = [
    "ALTER TABLE selection_events ADD INDEX IF NOT EXISTS window_seal greatest(timestamp_ms + window_ms, ledger_ms) TYPE minmax GRANULARITY 4",
    "ALTER TABLE metric_events ADD INDEX IF NOT EXISTS ledger_time ledger_ms TYPE minmax GRANULARITY 4",
]


def create_tables(client: Client, ttl_days: int = 90) -> None:
    """create clickhouse tables for event storage."""
    client.command(SELECTION_EVENTS_TABLE.format(ttl_days=ttl_days))
    client.command(FEEDBACK_EVENTS_TABLE.format(ttl_days=ttl_days))
    client.command(AUDIT_EVENTS_TABLE.format(ttl_days=ttl_days))
    client.command(METRIC_EVENTS_TABLE.format(ttl_days=ttl_days))
    client.command(SEALED_DECISIONS_TABLE.format(ttl_days=ttl_days))
    for alter in SELECTION_EVENTS_ALTERS + METRIC_EVENTS_ALTERS + LEDGER_INDEXES:
        client.command(alter)


def drop_tables(client: Client) -> None:
    """drop clickhouse tables."""
    client.command(DROP_SELECTION_EVENTS)
    client.command(DROP_FEEDBACK_EVENTS)
    client.command(DROP_AUDIT_EVENTS)
    client.command(DROP_METRIC_EVENTS)
    client.command(DROP_SEALED_DECISIONS)


def create_database(client: Client, database: str) -> None:
    """create database if it doesn't exist."""
    client.command(f"CREATE DATABASE IF NOT EXISTS {database}")

from __future__ import annotations

import json
import math
from typing import Sequence

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from qbrixstore.event import AuditEvent
from qbrixstore.event import SelectionEvent
from qbrixstore.event import FeedbackEvent
from qbrixstore.config import ClickHouseSettings


class ClickHouseClient:
    """client for batch inserting events to clickhouse."""

    SELECTION_COLUMNS = [
        "tenant_id",
        "experiment_id",
        "request_id",
        "event_id",
        "arm_id",
        "arm_name",
        "arm_index",
        "is_default",
        "context_id",
        "context_vector",
        "context_metadata",
        "timestamp_ms",
        "policy",
    ]

    FEEDBACK_COLUMNS = [
        "tenant_id",
        "experiment_id",
        "request_id",
        "arm_index",
        "reward",
        "context_id",
        "context_vector",
        "context_metadata",
        "timestamp_ms",
    ]

    AUDIT_COLUMNS = [
        "name",
        "tenant_id",
        "actor_id",
        "resource_type",
        "resource_id",
        "payload",
        "timestamp_ms",
    ]

    def __init__(self, settings: ClickHouseSettings | None = None):
        if settings is None:
            settings = ClickHouseSettings()
        self._settings = settings
        self._client: Client | None = None

    def connect(self, create_database: bool = True) -> None:
        if create_database:
            init_client = clickhouse_connect.get_client(
                host=self._settings.host,
                port=self._settings.port,
                username=self._settings.user,
                password=self._settings.password,
            )
            init_client.command(
                f"CREATE DATABASE IF NOT EXISTS {self._settings.database}"
            )
            init_client.close()

        self._client = clickhouse_connect.get_client(
            host=self._settings.host,
            port=self._settings.port,
            username=self._settings.user,
            password=self._settings.password,
            database=self._settings.database,
        )

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    @staticmethod
    def _managed_float(value) -> float | None:
        """convert nan/inf to None for JSON-safe output."""
        if value is None:
            return None
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)

    @property
    def client(self) -> Client:
        if self._client is None:
            raise RuntimeError("ClickHouse client not connected. Call connect() first.")
        return self._client

    def insert_selection_events(self, events: Sequence[SelectionEvent]) -> None:
        """batch insert selection events."""
        if not events:
            return

        rows = [self._selection_to_row(event) for event in events]
        self.client.insert(
            table="selection_events",
            data=rows,
            column_names=self.SELECTION_COLUMNS,
        )

    def insert_feedback_events(self, events: Sequence[FeedbackEvent]) -> None:
        """batch insert feedback events."""
        if not events:
            return

        rows = [self._feedback_to_row(event) for event in events]
        self.client.insert(
            table="feedback_events",
            data=rows,
            column_names=self.FEEDBACK_COLUMNS,
        )

    @staticmethod
    def _selection_to_row(event: SelectionEvent) -> tuple:
        """convert selection event to clickhouse row tuple."""
        return (
            event.tenant_id,
            event.experiment_id,
            event.request_id,
            event.event_id,
            event.arm_id,
            event.arm_name,
            event.arm_index,
            event.is_default,
            event.context_id,
            event.context_vector,
            json.dumps(event.context_metadata),
            event.timestamp_ms,
            event.policy,
        )

    @staticmethod
    def _feedback_to_row(event: FeedbackEvent) -> tuple:
        """convert feedback event to clickhouse row tuple."""
        return (
            event.tenant_id,
            event.experiment_id,
            event.request_id,
            event.arm_index,
            event.reward,
            event.context_id,
            event.context_vector,
            json.dumps(event.context_metadata),
            event.timestamp_ms,
        )

    def insert_audit_events(self, events: Sequence[AuditEvent]) -> None:
        """batch insert audit events."""
        if not events:
            return

        rows = [self._audit_to_row(event) for event in events]
        self.client.insert(
            table="audit_events",
            data=rows,
            column_names=self.AUDIT_COLUMNS,
        )

    @staticmethod
    def _audit_to_row(event: AuditEvent) -> tuple:
        """convert audit event to clickhouse row tuple."""
        return (
            event.name,
            event.tenant_id,
            event.actor_id,
            event.resource_type,
            event.resource_id,
            json.dumps(event.payload),
            event.timestamp_ms,
        )

    def query_selection_events(
        self,
        tenant_id: str,
        experiment_id: str | None = None,
        request_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """query selection events with optional filters."""
        conditions = ["tenant_id = {tenant_id:String}"]
        params = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

        if experiment_id:
            conditions.append("experiment_id = {experiment_id:String}")
            params["experiment_id"] = experiment_id

        if request_id:
            conditions.append("request_id = {request_id:String}")
            params["request_id"] = request_id

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT *
            FROM selection_events
            WHERE {where_clause}
            ORDER BY timestamp_ms DESC
            LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
        """

        result = self.client.query(query, parameters=params)
        return [dict(zip(result.column_names, row)) for row in result.result_rows]

    def query_feedback_events(
        self,
        tenant_id: str,
        experiment_id: str | None = None,
        request_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """query feedback events with optional filters."""
        conditions = ["tenant_id = {tenant_id:String}"]
        params = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

        if experiment_id:
            conditions.append("experiment_id = {experiment_id:String}")
            params["experiment_id"] = experiment_id

        if request_id:
            conditions.append("request_id = {request_id:String}")
            params["request_id"] = request_id

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT *
            FROM feedback_events
            WHERE {where_clause}
            ORDER BY timestamp_ms DESC
            LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
        """

        result = self.client.query(query, parameters=params)
        return [dict(zip(result.column_names, row)) for row in result.result_rows]

    @staticmethod
    def _experiment_filter(
        experiment_id: str | list[str],
        conditions: list[str],
        params: dict,
    ) -> None:
        """add experiment_id filter to conditions/params. supports single or multi-id."""
        if isinstance(experiment_id, list):
            conditions.append("experiment_id IN {experiment_ids:Array(String)}")
            params["experiment_ids"] = experiment_id
        else:
            conditions.append("experiment_id = {experiment_id:String}")
            params["experiment_id"] = experiment_id

    def get_experiment_stats(
        self,
        tenant_id: str,
        experiment_id: str | list[str],
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> dict:
        """get aggregated stats for an experiment (or multiple child experiments)."""
        conditions = ["tenant_id = {tenant_id:String}"]
        params = {"tenant_id": tenant_id}
        self._experiment_filter(experiment_id, conditions, params)

        if start_ms:
            conditions.append("timestamp_ms >= {start_ms:Int64}")
            params["start_ms"] = start_ms  # noqa

        if end_ms:
            conditions.append("timestamp_ms < {end_ms:Int64}")
            params["end_ms"] = end_ms  # noqa

        where_clause = " AND ".join(conditions)

        selection_query = f"""
            SELECT
                count() as total_selections,
                countIf(is_default = true) as default_selections,
                uniqExact(context_id) as unique_contexts,
                min(timestamp_ms) as first_selection_ms,
                max(timestamp_ms) as last_selection_ms
            FROM selection_events
            WHERE {where_clause}
        """

        feedback_query = f"""
            SELECT
                count() as total_feedback,
                avg(reward) as avg_reward,
                min(reward) as min_reward,
                max(reward) as max_reward
            FROM feedback_events
            WHERE {where_clause}
        """

        selection_result = self.client.query(selection_query, parameters=params)
        feedback_result = self.client.query(feedback_query, parameters=params)

        sel_row = (
            selection_result.result_rows[0]
            if selection_result.result_rows
            else [0, 0, 0, 0, 0]
        )
        fb_row = (
            feedback_result.result_rows[0]
            if feedback_result.result_rows
            else [0, None, None, None]
        )

        return {
            "total_selections": sel_row[0],
            "default_selections": sel_row[1],
            "unique_contexts": sel_row[2],
            "first_selection_ms": sel_row[3],
            "last_selection_ms": sel_row[4],
            "total_feedback": fb_row[0],
            "avg_reward": self._managed_float(fb_row[1]),
            "min_reward": self._managed_float(fb_row[2]),
            "max_reward": self._managed_float(fb_row[3]),
        }

    def count_distinct_selections(
        self, tenant_id: str, start_ms: int, end_ms: int
    ) -> int:
        """deduped selection count for a tenant over [start_ms, end_ms).

        uses uniqExact(event_id), computed across all parts at query time, so the
        count is exact and independent of merge timing. retained for internal
        usage lookup / auditing against the immutable selection event log.
        """
        query = """
            SELECT uniqExact(event_id) as billable_selections
            FROM selection_events
            WHERE tenant_id = {tenant_id:String}
              AND timestamp_ms >= {start_ms:Int64}
              AND timestamp_ms < {end_ms:Int64}
        """
        params = {"tenant_id": tenant_id, "start_ms": start_ms, "end_ms": end_ms}
        result = self.client.query(query, parameters=params)
        if not result.result_rows:
            return 0
        return int(result.result_rows[0][0])

    def get_experiment_timeseries(
        self,
        tenant_id: str,
        experiment_id: str | list[str],
        interval_ms: int = 3600000,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[dict]:
        """get time series data for an experiment (or multiple child experiments)."""
        conditions = ["tenant_id = {tenant_id:String}"]
        params = {
            "tenant_id": tenant_id,
            "interval_ms": interval_ms,
        }
        self._experiment_filter(experiment_id, conditions, params)

        if start_ms:
            conditions.append("timestamp_ms >= {start_ms:Int64}")
            params["start_ms"] = start_ms

        if end_ms:
            conditions.append("timestamp_ms < {end_ms:Int64}")
            params["end_ms"] = end_ms

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT
                intDiv(timestamp_ms, {{interval_ms:Int64}}) * {{interval_ms:Int64}} as bucket,
                count() as selections,
                countIf(is_default = true) as default_selections
            FROM selection_events
            WHERE {where_clause}
            GROUP BY bucket
            ORDER BY bucket ASC
        """

        result = self.client.query(query, parameters=params)
        return [
            {"timestamp_ms": row[0], "selections": row[1], "default_selections": row[2]}
            for row in result.result_rows
        ]

    def get_arm_stats(
        self,
        tenant_id: str,
        experiment_id: str | list[str],
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[dict]:
        """get per-arm statistics for an experiment (or multiple child experiments)."""
        conditions = ["tenant_id = {tenant_id:String}"]
        params = {"tenant_id": tenant_id}
        self._experiment_filter(experiment_id, conditions, params)

        if start_ms:
            conditions.append("timestamp_ms >= {start_ms:Int64}")
            params["start_ms"] = start_ms  # noqa

        if end_ms:
            conditions.append("timestamp_ms < {end_ms:Int64}")
            params["end_ms"] = end_ms  # noqa

        where_clause = " AND ".join(conditions)

        selection_query = f"""
            SELECT
                arm_index,
                arm_name,
                count() as selections
            FROM selection_events
            WHERE {where_clause}
            GROUP BY arm_index, arm_name
            ORDER BY arm_index
        """

        feedback_query = f"""
            SELECT
                arm_index,
                count() as feedback_count,
                avg(reward) as avg_reward
            FROM feedback_events
            WHERE {where_clause}
            GROUP BY arm_index
        """

        selection_result = self.client.query(selection_query, parameters=params)
        feedback_result = self.client.query(feedback_query, parameters=params)

        feedback_map = {
            row[0]: {
                "feedback_count": row[1],
                "avg_reward": self._managed_float(row[2]),
            }
            for row in feedback_result.result_rows
        }

        return [
            {
                "arm_index": row[0],
                "arm_name": row[1],
                "selections": row[2],
                "feedback_count": feedback_map.get(row[0], {}).get("feedback_count", 0),
                "avg_reward": feedback_map.get(row[0], {}).get("avg_reward"),
            }
            for row in selection_result.result_rows
        ]

    def get_arm_stats_batch(
        self,
        tenant_id: str,
        experiment_ids: Sequence[str],
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> dict[str, list[dict]]:
        """per-arm statistics for many experiments in two queries, not two per id.

        the per-experiment `get_arm_stats` is the same aggregation with the id
        pinned; a workspace view calling it in a loop costs 2N clickhouse round
        trips for a table that renders in one frame. keyed by experiment_id, and
        experiments with no events are absent rather than empty.
        """
        if not experiment_ids:
            return {}

        conditions = [
            "tenant_id = {tenant_id:String}",
            "experiment_id IN {experiment_ids:Array(String)}",
        ]
        params: dict = {
            "tenant_id": tenant_id,
            "experiment_ids": list(experiment_ids),
        }

        if start_ms:
            conditions.append("timestamp_ms >= {start_ms:Int64}")
            params["start_ms"] = start_ms

        if end_ms:
            conditions.append("timestamp_ms < {end_ms:Int64}")
            params["end_ms"] = end_ms

        where_clause = " AND ".join(conditions)

        selection_query = f"""
            SELECT
                experiment_id,
                arm_index,
                arm_name,
                count() as selections
            FROM selection_events
            WHERE {where_clause}
            GROUP BY experiment_id, arm_index, arm_name
            ORDER BY experiment_id, arm_index
        """

        feedback_query = f"""
            SELECT
                experiment_id,
                arm_index,
                count() as feedback_count,
                sum(reward) as reward_sum
            FROM feedback_events
            WHERE {where_clause}
            GROUP BY experiment_id, arm_index
        """

        selection_result = self.client.query(selection_query, parameters=params)
        feedback_result = self.client.query(feedback_query, parameters=params)

        # reward is carried as a sum, not a mean: the caller folds meta-bandit
        # learners into their parent, and means cannot be summed across them.
        feedback_map = {
            (row[0], row[1]): {"feedback_count": row[2], "reward_sum": row[3]}
            for row in feedback_result.result_rows
        }

        out: dict[str, list[dict]] = {}
        for row in selection_result.result_rows:
            experiment_id, arm_index, arm_name, selections = row
            fb = feedback_map.get((experiment_id, arm_index), {})
            out.setdefault(experiment_id, []).append(
                {
                    "arm_index": arm_index,
                    "arm_name": arm_name,
                    "selections": selections,
                    "feedback_count": fb.get("feedback_count", 0),
                    "reward_sum": self._managed_float(fb.get("reward_sum")) or 0.0,
                }
            )
        return out

    def get_reward_timeseries(
        self,
        tenant_id: str,
        experiment_id: str | list[str],
        interval_ms: int,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[dict]:
        """get bucketed avg reward over time from feedback events."""
        conditions = ["tenant_id = {tenant_id:String}"]
        params: dict = {
            "tenant_id": tenant_id,
            "interval_ms": interval_ms,
        }
        self._experiment_filter(experiment_id, conditions, params)

        if start_ms:
            conditions.append("timestamp_ms >= {start_ms:Int64}")
            params["start_ms"] = start_ms

        if end_ms:
            conditions.append("timestamp_ms < {end_ms:Int64}")
            params["end_ms"] = end_ms

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT
                intDiv(timestamp_ms, {{interval_ms:Int64}}) * {{interval_ms:Int64}} as bucket,
                avg(reward) as avg_reward,
                count() as feedback_count
            FROM feedback_events
            WHERE {where_clause}
            GROUP BY bucket
            ORDER BY bucket ASC
        """

        result = self.client.query(query, parameters=params)
        return [
            {
                "timestamp_ms": row[0],
                "avg_reward": self._managed_float(row[1]) or 0.0,
                "feedback_count": row[2],
            }
            for row in result.result_rows
        ]

    def get_arm_timeseries(
        self,
        tenant_id: str,
        experiment_id: str | list[str],
        interval_ms: int,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[dict]:
        """get per-arm selections per time bucket from selection events."""
        conditions = ["tenant_id = {tenant_id:String}"]
        params: dict = {
            "tenant_id": tenant_id,
            "interval_ms": interval_ms,
        }
        self._experiment_filter(experiment_id, conditions, params)

        if start_ms:
            conditions.append("timestamp_ms >= {start_ms:Int64}")
            params["start_ms"] = start_ms

        if end_ms:
            conditions.append("timestamp_ms < {end_ms:Int64}")
            params["end_ms"] = end_ms

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT
                intDiv(timestamp_ms, {{interval_ms:Int64}}) * {{interval_ms:Int64}} as bucket,
                arm_index,
                arm_name,
                count() as selections
            FROM selection_events
            WHERE {where_clause}
            GROUP BY bucket, arm_index, arm_name
            ORDER BY bucket ASC
        """

        result = self.client.query(query, parameters=params)

        # pivot: group rows by bucket, collect arms into list
        buckets: dict[int, list[dict]] = {}
        for row in result.result_rows:
            bucket_ms, arm_index, arm_name, selections = row[0], row[1], row[2], row[3]
            if bucket_ms not in buckets:
                buckets[bucket_ms] = []
            buckets[bucket_ms].append(
                {"arm_index": arm_index, "arm_name": arm_name, "selections": selections}
            )

        return [
            {"timestamp_ms": bucket_ms, "arms": arms}
            for bucket_ms, arms in sorted(buckets.items())
        ]

    def get_feedback_funnel(
        self,
        tenant_id: str,
        experiment_id: str | list[str],
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> dict:
        """get selection vs feedback funnel metrics."""
        conditions = ["tenant_id = {tenant_id:String}"]
        params: dict = {"tenant_id": tenant_id}
        self._experiment_filter(experiment_id, conditions, params)

        if start_ms:
            conditions.append("timestamp_ms >= {start_ms:Int64}")
            params["start_ms"] = start_ms  # noqa

        if end_ms:
            conditions.append("timestamp_ms < {end_ms:Int64}")
            params["end_ms"] = end_ms  # noqa

        where_clause = " AND ".join(conditions)

        selection_query = f"""
            SELECT count()
            FROM selection_events
            WHERE {where_clause}
        """

        feedback_query = f"""
            SELECT count()
            FROM feedback_events
            WHERE {where_clause}
        """

        selection_result = self.client.query(selection_query, parameters=params)
        feedback_result = self.client.query(feedback_query, parameters=params)

        total_selections = (
            selection_result.result_rows[0][0] if selection_result.result_rows else 0
        )
        total_feedback = (
            feedback_result.result_rows[0][0] if feedback_result.result_rows else 0
        )

        feedback_rate = (
            total_feedback / total_selections if total_selections > 0 else 0.0
        )

        return {
            "total_selections": total_selections,
            "total_feedback": total_feedback,
            "feedback_rate": feedback_rate,
        }

    def get_cumulative_reward(
        self,
        tenant_id: str,
        experiment_id: str | list[str],
        interval_ms: int,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[dict]:
        """get cumulative reward over time, computed from bucketed sums."""
        conditions = ["tenant_id = {tenant_id:String}"]
        params: dict = {
            "tenant_id": tenant_id,
            "interval_ms": interval_ms,
        }
        self._experiment_filter(experiment_id, conditions, params)

        if start_ms:
            conditions.append("timestamp_ms >= {start_ms:Int64}")
            params["start_ms"] = start_ms

        if end_ms:
            conditions.append("timestamp_ms < {end_ms:Int64}")
            params["end_ms"] = end_ms

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT
                intDiv(timestamp_ms, {{interval_ms:Int64}}) * {{interval_ms:Int64}} as bucket,
                sum(reward) as bucket_reward,
                count() as bucket_count
            FROM feedback_events
            WHERE {where_clause}
            GROUP BY bucket
            ORDER BY bucket ASC
        """

        result = self.client.query(query, parameters=params)

        # running sum computed in python after sql
        cumulative_reward = 0.0
        cumulative_count = 0
        points = []
        for row in result.result_rows:
            bucket_ms, bucket_reward, bucket_count = row[0], row[1], row[2]
            cumulative_reward += self._managed_float(bucket_reward) or 0.0
            cumulative_count += bucket_count
            points.append(
                {
                    "timestamp_ms": bucket_ms,
                    "cumulative_reward": cumulative_reward,
                    "cumulative_count": cumulative_count,
                }
            )

        return points

    def query_audit_events(
        self,
        tenant_id: str,
        name: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """query audit events with optional filters."""
        conditions = ["tenant_id = {tenant_id:String}"]
        params: dict = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

        if name:
            conditions.append("name = {name:String}")
            params["name"] = name

        if resource_type:
            conditions.append("resource_type = {resource_type:String}")
            params["resource_type"] = resource_type

        if resource_id:
            conditions.append("resource_id = {resource_id:String}")
            params["resource_id"] = resource_id

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT *
            FROM audit_events
            WHERE {where_clause}
            ORDER BY timestamp_ms DESC
            LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
        """

        result = self.client.query(query, parameters=params)
        return [dict(zip(result.column_names, row)) for row in result.result_rows]

    def query_events(
        self,
        tenant_id: str,
        event_category: str | None = None,
        resource_id: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """query unified event log across selection, feedback, and audit tables.

        event_category: "selection", "feedback", "audit", or None for all.
        """
        params: dict = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

        def _build_subquery(category: str) -> str:
            if category == "selection":
                table = "selection_events"
                name_expr = "'selection.completed'"
                rid_expr = "experiment_id"
                data_fields = (
                    "map('request_id', request_id, 'arm_id', arm_id, "
                    "'arm_name', arm_name, 'arm_index', toString(arm_index), "
                    "'is_default', if(is_default, 'true', 'false'), "
                    "'context_id', context_id, 'policy', policy)"
                )
            elif category == "feedback":
                table = "feedback_events"
                name_expr = "'feedback.received'"
                rid_expr = "experiment_id"
                data_fields = (
                    "map('request_id', request_id, 'arm_index', toString(arm_index), "
                    "'reward', toString(reward), 'context_id', context_id)"
                )
            else:
                table = "audit_events"
                name_expr = "name"
                rid_expr = "resource_id"
                data_fields = (
                    "map('payload', payload, 'actor_id', actor_id, "
                    "'resource_type', resource_type)"
                )

            conditions = ["tenant_id = {tenant_id:String}"]

            if resource_id:
                conditions.append(f"{rid_expr} = {{resource_id:String}}")

            if start_ms:
                conditions.append("timestamp_ms >= {start_ms:Int64}")

            if end_ms:
                conditions.append("timestamp_ms < {end_ms:Int64}")

            where = " AND ".join(conditions)
            return f"""
                SELECT
                    {name_expr} as name,
                    tenant_id,
                    {rid_expr} as resource_id,
                    timestamp_ms,
                    '{category}' as category,
                    {data_fields} as data
                FROM {table}
                WHERE {where}
            """

        if resource_id:
            params["resource_id"] = resource_id
        if start_ms:
            params["start_ms"] = start_ms
        if end_ms:
            params["end_ms"] = end_ms

        categories = (
            [event_category]
            if event_category in ("selection", "feedback", "audit")
            else ["selection", "feedback", "audit"]
        )

        subqueries = " UNION ALL ".join(_build_subquery(c) for c in categories)
        query = f"""
            SELECT name, tenant_id, resource_id, timestamp_ms, category, data
            FROM ({subqueries})
            ORDER BY timestamp_ms DESC
            LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
        """

        result = self.client.query(query, parameters=params)
        return [
            {
                "name": row[0],
                "tenant_id": row[1],
                "resource_id": row[2],
                "timestamp_ms": row[3],
                "category": row[4],
                "data": row[5],
            }
            for row in result.result_rows
        ]

    def health_check(self) -> bool:
        """check if clickhouse is healthy."""
        try:
            result = self.client.query("SELECT 1")
            return result.result_rows == [(1,)]
        except Exception:  # noqa
            return False

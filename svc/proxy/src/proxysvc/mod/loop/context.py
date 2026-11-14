from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from datetime import timezone

from qbrixcore.context_schema import ContextSchema
from qbrixcore.engine import ENGINES
from qbrixstore.clickhouse.ledger import PropertyArrival
from qbrixstore.postgres.models import Loop

from proxysvc.mod.loop.stat import DAY_MS

ARRIVALS_MS = DAY_MS
_NULL = "Null"


def context_read(
    loop: Loop, decisions: int, arrivals: list[PropertyArrival], since_ms: int
) -> dict:
    """a loop's declared context, and what its decisions actually carried:
    for each declared property how many carried it and how many of those
    values it can learn from, and the properties sent but not declared.

    a value of the wrong type is learned as its default, so arrived and
    readable differ exactly when the app and the schema disagree.
    """
    schema = (
        ContextSchema.model_validate(loop.context_schema)
        if loop.context_schema
        else None
    )
    seen: dict[str, list[PropertyArrival]] = defaultdict(list)
    for arrival in arrivals:
        if arrival.type != _NULL:
            seen[arrival.name].append(arrival)

    declared = []
    for prop in schema.root if schema else ():
        rows = seen.get(prop.name, [])
        latest = max(rows, key=lambda row: row.last_ms, default=None)
        declared.append(
            {
                "name": prop.name,
                "type": prop.type,
                "arrived": sum(row.arrived for row in rows),
                "readable": sum(
                    row.arrived
                    for row in rows
                    if schema.readable(prop.name, json.loads(row.last))
                ),
                "last_value": json.loads(latest.last) if latest else None,
            }
        )

    names = {prop["name"] for prop in declared}
    undeclared = sorted(
        (
            {"name": name, "arrived": sum(row.arrived for row in rows)}
            for name, rows in seen.items()
            if name not in names
        ),
        key=lambda prop: (-prop["arrived"], prop["name"]),
    )
    return {
        "context": loop.context_schema,
        "learns_from_context": ENGINES.get(loop.engine).needs_context,
        "since": datetime.fromtimestamp(since_ms / 1000, timezone.utc).isoformat(),
        "decisions": decisions,
        "properties": declared,
        "undeclared": undeclared,
    }

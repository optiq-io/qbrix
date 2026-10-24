from __future__ import annotations

from qbrixcore.engine import Resolved
from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.models import LoopOption


def _stamp(value) -> str | None:
    return value.isoformat() if value else None


def option_to_dict(option: LoopOption) -> dict:
    return {
        "id": option.id,
        "key": option.key,
        "name": option.name,
        "config": option.config or {},
    }


def cycle_to_dict(cycle: Cycle) -> dict:
    version = cycle.metric_version
    return {
        "id": cycle.id,
        "number": cycle.number,
        "engine": cycle.engine,
        "engine_version": cycle.engine_version,
        "metric_version": f"{version.major}.{version.minor}",
        "started_at": _stamp(cycle.started_at),
        "ended_at": _stamp(cycle.ended_at),
    }


def loop_to_dict(loop: Loop) -> dict:
    return {
        "id": loop.id,
        "key": loop.key,
        "name": loop.name,
        "purpose": loop.purpose,
        "metric": {"id": loop.metric.id, "name": loop.metric.name},
        "engine": loop.engine,
        "state": loop.state,
        "paused_from": loop.paused_from,
        "owner": loop.owner_user_id,
        "fallback": loop.fallback_key,
        "options": [option_to_dict(option) for option in loop.options],
        "cycle": cycle_to_dict(loop.cycles[-1]) if loop.cycles else None,
        "created_at": _stamp(loop.created_at),
        "updated_at": _stamp(loop.updated_at),
    }


def cycle_record(tenant_id: str, loop: Loop, cycle: Cycle, resolved: Resolved) -> dict:
    """a live cycle as the record motor serves and cortex trains, under the
    cycle's id: the options are the arms, in the cycle's order."""
    return {
        "id": cycle.id,
        "tenant_id": tenant_id,
        "loop_id": loop.id,
        "name": loop.name,
        "pool_id": loop.id,
        "pool": {
            "id": loop.id,
            "name": loop.key,
            "arms": [
                {
                    "id": option["id"],
                    "name": option["key"],
                    "index": index,
                    "is_active": True,
                    "metadata": option["config"],
                }
                for index, option in enumerate(cycle.options)
            ],
        },
        "policy": resolved.policy_cls.name,
        "policy_params": dict(resolved.fixed_params),
        "enabled": True,
    }

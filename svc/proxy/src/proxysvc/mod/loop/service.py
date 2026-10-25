from __future__ import annotations

import re
from typing import Any

from sqlalchemy.exc import IntegrityError

from qbrixcore.engine import ENGINES
from qbrixcore.engine import EngineError
from qbrixcore.engine import EngineSpec
from qbrixcore.engine import Resolved
from qbrixcore.engine import ScoreRange
from qbrixcore.engine import check_metric
from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.models import LoopOption
from qbrixstore.postgres.models import Metric
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.client import RedisClient

from proxysvc.core.actor import Actor
from proxysvc.core.error import LoopInvalidError
from proxysvc.core.error import LoopKeyTakenError
from proxysvc.core.error import LoopStateError
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.undo import Undoing
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.loop.route import LoopRouteCache
from proxysvc.mod.loop.route import route_of
from proxysvc.mod.loop.serialize import cycle_record
from proxysvc.mod.loop.serialize import loop_to_dict
from proxysvc.mod.loop.serialize import option_to_dict
from proxysvc.mod.metric.repository import MetricRepository

KEY_MAX_LENGTH = 64
MIN_OPTIONS = 2

_KEY = re.compile(r"[a-z0-9][a-z0-9_.-]*")
_NOT_KEY = re.compile(r"[^a-z0-9]+")
_GENERATED_MAX_LENGTH = KEY_MAX_LENGTH - len("-999")


def _check_key(key: str, what: str) -> str:
    if len(key) > KEY_MAX_LENGTH or not _KEY.fullmatch(key):
        raise LoopInvalidError(
            f"{what} key is what code calls: lowercase letters, digits, '_', '-' "
            f"and '.', starting with a letter or digit, at most {KEY_MAX_LENGTH} "
            f"characters, got {key!r}"
        )
    return key


def _key_from(name: str, default: str) -> str:
    slug = _NOT_KEY.sub("-", name.lower()).strip("-")
    return slug[:_GENERATED_MAX_LENGTH].rstrip("-") or default


def _unique(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _name(name: str, what: str) -> str:
    name = name.strip()
    if not name:
        raise LoopInvalidError(f"{what} needs a name")
    return name


def _taken(key: str) -> LoopKeyTakenError:
    return LoopKeyTakenError(f"a loop with the key {key!r} already exists")


def _not_draft(loop_key: str, state: str, refused: str) -> LoopStateError:
    return LoopStateError(f"{refused}: the loop {loop_key!r} is {state}, not a draft")


def _options(options: list[dict[str, Any]]) -> list[LoopOption]:
    if len(options) < MIN_OPTIONS:
        raise LoopInvalidError(
            f"a loop needs at least {MIN_OPTIONS} options, got {len(options)}"
        )
    given = [o["key"] for o in options if o.get("key") is not None]
    taken: set[str] = set()
    for key in given:
        _check_key(key, "an option")
        if key in taken:
            raise LoopInvalidError(f"two options have the key {key!r}")
        taken.add(key)
    built = []
    for position, option in enumerate(options):
        name = _name(option.get("name") or "", "every option")
        key = option.get("key")
        if key is None:
            key = _unique(_key_from(name, "option"), taken)
            taken.add(key)
        built.append(
            LoopOption(
                key=key,
                name=name,
                config=option.get("config") or {},
                position=position,
            )
        )
    return built


def _engine(engine: str) -> str:
    try:
        return str(EngineSpec.parse(engine))
    except EngineError as e:
        raise LoopInvalidError(str(e)) from e


def _resolve(engine: str, metric: Metric) -> Resolved:
    score_range = (
        ScoreRange(metric.score_lo, metric.score_hi)
        if metric.score_lo is not None
        else None
    )
    try:
        metric_type = check_metric(metric.type, score_range)
        return ENGINES.get(engine).resolve(metric_type, score_range=score_range)
    except EngineError as e:
        raise LoopInvalidError(str(e)) from e


class LoopService:
    """loops: created as drafts, launched into their first cycle, renamed.

    a live cycle is written to redis as the record motor serves and cortex
    trains, under the cycle's id, so a new cycle never mixes earlier learning.
    every write also rewrites the loop's route, which is all select reads.
    """

    def __init__(self, *, redis: RedisClient, routes: LoopRouteCache):
        self._redis = redis
        self._routes = routes

    async def create_loop(
        self,
        tenant_id: str,
        *,
        name: str,
        key: str | None = None,
        purpose: str = "",
        metric: str | None,
        engine: str = ENGINES.DEFAULT,
        options: list[dict[str, Any]],
        fallback: str | None = None,
        actor: Actor,
    ) -> dict:
        name = _name(name, "a loop")
        if key is not None:
            _check_key(key, "a loop")
        if not metric:
            raise LoopInvalidError("a loop needs a metric: the one it improves")
        built = _options(options)
        keys = [option.key for option in built]
        fallback = keys[0] if fallback is None else fallback
        if fallback not in keys:
            raise LoopInvalidError(
                f"the fallback {fallback!r} is not one of the loop's options "
                f"({', '.join(keys)})"
            )
        engine = _engine(engine)

        async with get_session() as session:
            found = await MetricRepository(session, tenant_id).resolve(metric)
            if found is None:
                raise LoopInvalidError(f"no metric named or with id {metric!r}")
            _resolve(engine, found)

            repo = LoopRepository(session, tenant_id)
            if key is None:
                base = _key_from(name, "loop")
                key = _unique(base, await repo.keys_from(base))
            elif await repo.get_by_key(key) is not None:
                raise _taken(key)
            try:
                loop = await repo.create(
                    key=key,
                    name=name,
                    purpose=purpose.strip(),
                    metric=found,
                    engine=engine,
                    owner_user_id=actor.user_id,
                    fallback_key=fallback,
                    options=built,
                )
            except IntegrityError as e:
                raise _taken(key) from e
            loop_dict = loop_to_dict(loop)
            route = route_of(loop)
            await ChangeRepository(session, tenant_id).record(
                "loop.create", "loop", loop.id, actor, after=loop_dict
            )
        await self._routes.put(tenant_id, route)
        return loop_dict

    async def launch_loop(
        self, tenant_id: str, ref: str, *, actor: Actor
    ) -> dict | None:
        async with get_session() as session:
            repo = LoopRepository(session, tenant_id)
            loop = await repo.resolve(ref)
            if loop is None:
                return None
            loop_key = loop.key
            if loop.state != "draft":
                raise _not_draft(loop_key, loop.state, "only a draft can be launched")
            resolved = _resolve(loop.engine, loop.metric)
            pinned = ENGINES.pin(loop.engine)
            before = loop_to_dict(loop)
            loop.cycles.append(
                Cycle(
                    number=1,
                    engine=str(pinned),
                    engine_version=str(ENGINES.get(pinned).version),
                    metric_version_id=loop.metric.versions[-1].id,
                    options=[option_to_dict(option) for option in loop.options],
                )
            )
            loop.state = "live"
            try:
                loop = await repo.reload(loop)
            except IntegrityError as e:
                raise _not_draft(
                    loop_key, "live", "only a draft can be launched"
                ) from e
            loop_dict = loop_to_dict(loop)
            record = cycle_record(tenant_id, loop, loop.cycles[-1], resolved)
            route = route_of(loop)
            await ChangeRepository(session, tenant_id).record(
                "loop.launch",
                "loop",
                loop.id,
                actor,
                before=before,
                after=loop_dict,
            )
        await self._redis.set_experiment(tenant_id, record["id"], record)
        await self._routes.put(tenant_id, route)
        return loop_dict

    async def rename_loop(
        self,
        tenant_id: str,
        ref: str,
        *,
        name: str | None = None,
        key: str | None = None,
        actor: Actor,
        undoing: Undoing | None = None,
    ) -> dict | None:
        """a new name at any time; a new key only while the loop is a draft."""
        if name is None and key is None:
            raise LoopInvalidError("a rename needs a new name, a new key or both")
        if name is not None:
            name = _name(name, "a loop")
        if key is not None:
            _check_key(key, "a loop")

        async with get_session() as session:
            repo = LoopRepository(session, tenant_id)
            loop = await repo.resolve(ref)
            if loop is None:
                return None
            if key is not None and key != loop.key:
                if loop.state != "draft":
                    raise _not_draft(
                        loop.key, loop.state, "the key locks when the loop is launched"
                    )
                if await repo.get_by_key(key) is not None:
                    raise _taken(key)
            before = loop_to_dict(loop)
            old_key = loop.key
            if name is not None:
                loop.name = name
            if key is not None:
                loop.key = key
            try:
                loop = await repo.reload(loop)
            except IntegrityError as e:
                raise _taken(key) from e
            loop_dict = loop_to_dict(loop)
            route = route_of(loop)
            await ChangeRepository(session, tenant_id).record(
                "loop.rename",
                "loop",
                loop.id,
                actor,
                before=before,
                after=loop_dict,
                undoing=undoing,
            )
        await self._routes.put(tenant_id, route, old_key=old_key)
        return loop_dict

    async def delete_loop(
        self,
        tenant_id: str,
        loop_id: str,
        *,
        actor: Actor,
        undoing: Undoing | None = None,
    ) -> bool:
        async with get_session() as session:
            repo = LoopRepository(session, tenant_id)
            loop = await repo.get(loop_id)
            if loop is None:
                return False
            if loop.state != "draft":
                raise _not_draft(loop.key, loop.state, "only a draft can be deleted")
            before = loop_to_dict(loop)
            loop_key = loop.key
            await repo.delete(loop)
            await ChangeRepository(session, tenant_id).record(
                "loop.delete",
                "loop",
                loop_id,
                actor,
                before=before,
                undoing=undoing,
            )
        await self._routes.drop(tenant_id, loop_id, loop_key)
        return True

    async def get_loop(self, tenant_id: str, ref: str) -> dict | None:
        async with get_session() as session:
            loop = await LoopRepository(session, tenant_id).resolve(ref)
            return loop_to_dict(loop) if loop else None

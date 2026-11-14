from __future__ import annotations

import re
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qbrixcore.context_schema import ContextSchema
from qbrixcore.engine import ENGINES
from qbrixcore.engine import EngineError
from qbrixcore.engine import EngineSpec
from qbrixcore.engine import Resolved
from qbrixcore.engine import ScoreRange
from qbrixcore.engine import check_metric
from qbrixstore.postgres.models import Change
from qbrixstore.postgres.models import Cycle
from qbrixstore.postgres.models import Loop
from qbrixstore.postgres.models import LoopOption
from qbrixstore.postgres.models import Metric
from qbrixstore.postgres.models import User
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.client import RedisClient

from proxysvc.core.actor import Actor
from proxysvc.core.error import LoopInvalidError
from proxysvc.core.error import LoopKeyTakenError
from proxysvc.core.error import LoopRetiredError
from proxysvc.core.error import LoopStateError
from proxysvc.mod.change.applied import Applied
from proxysvc.mod.change.note import NOTE
from proxysvc.mod.change.note import NOTE_MAX_LENGTH
from proxysvc.mod.change.repository import ChangeRepository
from proxysvc.mod.change.undo import Undoing
from proxysvc.mod.change.undo import is_undoable
from proxysvc.mod.loop.delivery import Delivery
from proxysvc.mod.loop.delivery import delivery_of
from proxysvc.mod.loop.edit import UNSET
from proxysvc.mod.loop.edit import StagedContext
from proxysvc.mod.loop.edit import Checked
from proxysvc.mod.loop.edit import Edited
from proxysvc.mod.loop.edit import Edits
from proxysvc.mod.loop.repository import LoopRepository
from proxysvc.mod.loop.route import LoopRoute
from proxysvc.mod.loop.route import LoopRouteCache
from proxysvc.mod.loop.route import route_of
from proxysvc.mod.loop.serialize import cycle_record
from proxysvc.mod.loop.serialize import loop_to_dict
from proxysvc.mod.loop.serialize import option_to_dict
from proxysvc.mod.metric.repository import MetricRepository
from proxysvc.mod.people import People

KEY_MAX_LENGTH = 64
MIN_OPTIONS = 2

_KEY = re.compile(r"[a-z0-9][a-z0-9_.-]*")
_NOT_KEY = re.compile(r"[^a-z0-9]+")
_GENERATED_MAX_LENGTH = KEY_MAX_LENGTH - len("-999")
# the console's create page lives at /next/loops/new, so a loop with this key could never open
_RESERVED_LOOP_KEYS = frozenset({"new"})


def _check_key(key: str, what: str) -> str:
    if len(key) > KEY_MAX_LENGTH or not _KEY.fullmatch(key):
        raise LoopInvalidError(
            f"{what} key is what code calls: lowercase letters, digits, '_', '-' "
            f"and '.', starting with a letter or digit, at most {KEY_MAX_LENGTH} "
            f"characters, got {key!r}"
        )
    return key


def _check_loop_key(key: str) -> str:
    _check_key(key, "a loop")
    if key in _RESERVED_LOOP_KEYS:
        raise LoopInvalidError(f"a loop can't have the key {key!r}: qbrix uses it")
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


_PAUSE_FIXES = {
    "draft": "a draft serves its fallback until it is launched",
    "paused": "it is paused already",
    "retired": "a retired loop serves its fallback already",
}
_RETIRE_FIXES = {
    "draft": "delete the draft instead",
    "retired": "it is retired already",
}
_CYCLE_FIXES = {
    "draft": "launch it first",
    "committed": "reopen it first",
    "retired": "create a new loop to serve the choice again",
}


def _refusing(refused: str, fixes: dict[str, str]) -> Callable[[Loop], None]:
    """a check that refuses the states in fixes, each with what to do instead."""

    def check(loop: Loop) -> None:
        fix = fixes.get(loop.state)
        if fix is not None:
            raise LoopStateError(
                f"{refused}: the loop {loop.key!r} is {loop.state}; {fix}"
            )

    return check


def _cyclable(refused: str) -> Callable[[Loop], None]:
    """a new cycle explores again, which a committed loop has stopped doing,
    and so has one paused from committed: resuming would return to the commit."""
    refusing = _refusing(refused, _CYCLE_FIXES)

    def check(loop: Loop) -> None:
        refusing(loop)
        if loop.state == "paused" and loop.paused_from == "committed":
            raise LoopStateError(
                f"{refused}: the loop {loop.key!r} is paused; it was committed "
                f"before the pause, so resume and reopen it first"
            )

    return check


_DELIVERY_FIXES = {
    "retired": "create a new loop to serve the choice again",
}


def _delivery(raw: dict[str, Any]) -> Delivery:
    try:
        return Delivery.model_validate(raw)
    except ValidationError as e:
        raise LoopInvalidError(
            "; ".join(_problem(error) for error in e.errors())
        ) from e


_UNION_TAGS = frozenset({"categorical", "numeric", "boolean"})


def _problem(error: dict[str, Any], prefix: str | None = None) -> str:
    message = error["msg"].removeprefix("Value error, ")
    loc = [part for part in error["loc"] if part not in _UNION_TAGS]
    where = ".".join(str(part) for part in ([prefix] if prefix else []) + loc)
    return f"{where}: {message}" if where else message


def _moved(loop_key: str, state: str, refused: str) -> LoopStateError:
    return LoopStateError(f"{refused}: the loop {loop_key!r} is {state}")


def _fallback_among(fallback: str, keys: list[str]) -> str:
    if fallback not in keys:
        raise LoopInvalidError(
            f"the fallback {fallback!r} is not one of the loop's options "
            f"({', '.join(keys)})"
        )
    return fallback


def _same_options(cycle: Cycle, options: list[LoopOption]) -> bool:
    return [(o["key"], o["name"], o["config"]) for o in cycle.options] == [
        (o.key, o.name, o.config) for o in options
    ]


def _replace_options(loop: Loop, options: list[LoopOption]) -> None:
    """a key that stays keeps its row, and with it its arm id."""
    kept = {option.key: option for option in loop.options}
    replaced = []
    for option in options:
        row = kept.get(option.key)
        if row is None:
            replaced.append(option)
            continue
        row.name = option.name
        row.config = option.config
        row.position = option.position
        replaced.append(row)
    loop.options = replaced


def _learns_from_context(engine: str) -> bool:
    return ENGINES.get(engine).needs_context


def starts_cycle(state: str, engine: str) -> bool:
    """whether declaring a loop's context starts a cycle: its engine learns
    from context, and the loop is past draft."""
    return state != "draft" and _learns_from_context(engine)


def _append_cycle(loop: Loop, engine: str) -> None:
    pinned = ENGINES.pin(engine)
    number = loop.cycles[-1].number + 1 if loop.cycles else 1
    loop.cycles.append(
        Cycle(
            number=number,
            engine=str(pinned),
            engine_version=str(ENGINES.get(pinned).version),
            metric_version_id=loop.metric.versions[-1].id,
            options=[option_to_dict(option) for option in loop.options],
            context_schema=(
                loop.context_schema if _learns_from_context(engine) else None
            ),
        )
    )


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


def _context(raw: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if raw is None:
        return None
    try:
        return ContextSchema.model_validate(raw).model_dump()
    except ValidationError as e:
        raise LoopInvalidError(
            "; ".join(_problem(error, "context") for error in e.errors())
        ) from e


def _check_context(
    loop: Loop, context: list[dict[str, Any]] | None, engine: str
) -> None:
    if context == loop.context_schema:
        raise LoopInvalidError("nothing changes: the context is the loop's own")
    if context is None and _learns_from_context(engine):
        raise LoopInvalidError(
            f"{ENGINES.get(engine).name} learns from context, so the context "
            f"can't be cleared; start a cycle on another engine first"
        )


def _engine(engine: str) -> str:
    try:
        return str(EngineSpec.parse(engine))
    except EngineError as e:
        raise LoopInvalidError(str(e)) from e


async def _owner(session: AsyncSession, tenant_id: str, loop: Loop) -> People:
    return await People.load(session, tenant_id, [loop.owner_user_id])


def _resolve(
    engine: str, metric: Metric, context: list[dict[str, Any]] | None = None
) -> Resolved:
    score_range = (
        ScoreRange(metric.score_lo, metric.score_hi)
        if metric.score_lo is not None
        else None
    )
    try:
        metric_type = check_metric(metric.type, score_range)
        return ENGINES.get(engine).resolve(
            metric_type,
            score_range=score_range,
            context_dim=ContextSchema.model_validate(context).dim if context else None,
        )
    except EngineError as e:
        raise LoopInvalidError(str(e)) from e


async def _metric(session: AsyncSession, tenant_id: str, ref: str) -> Metric:
    found = await MetricRepository(session, tenant_id).resolve(ref)
    if found is None:
        raise LoopInvalidError(f"no metric named or with id {ref!r}")
    return found


async def _member(session: AsyncSession, tenant_id: str, ref: str) -> str:
    """a member of the workspace by id or email, as their id."""
    stmt = select(User.id).where(
        User.tenant_id == tenant_id,
        User.is_active.is_(True),
        or_(User.id == ref, User.email == ref),
    )
    found = (await session.execute(stmt)).scalar_one_or_none()
    if found is None:
        raise LoopInvalidError(
            f"the owner must be a member of this workspace; no member {ref!r}"
        )
    return found


def _brief_of(loop: dict[str, Any]) -> tuple:
    return (
        loop["purpose"],
        loop["owner"]["id"],
        [(o["key"], o["name"], o["config"]) for o in loop["options"]],
        loop["engine"],
        loop["metric"]["id"],
        loop["fallback"],
    )


@contextmanager
def _part(name: str) -> Iterator[None]:
    """a refusal names the part of the edits it refused."""
    try:
        yield
    except (LoopInvalidError, LoopStateError) as e:
        raise type(e)(f"{name}: {e}") from e


def _planned(written: _Written, parts: tuple[str, ...], kept: bool) -> dict[str, Any]:
    change = written.change
    return {
        "id": change.id if kept else None,
        "kind": change.kind,
        "parts": list(parts),
        "undoable": is_undoable(change.kind, change.before, change.after),
    }


@dataclass(frozen=True, slots=True)
class _Written:
    """a write done in the caller's session: the caller puts its cycle record
    and route once the session commits."""

    loop: dict[str, Any]
    change: Change
    route: LoopRoute
    record: dict[str, Any] | None


class LoopService:
    """loops: created as drafts, launched into their first cycle, renamed,
    committed and reopened, paused and resumed, moved to a new cycle, and
    retired.

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
        reason: str | None = None,
    ) -> Applied:
        name = _name(name, "a loop")
        if key is not None:
            _check_loop_key(key)
        if not metric:
            raise LoopInvalidError("a loop needs a metric: the one it improves")
        built = _options(options)
        keys = [option.key for option in built]
        fallback = _fallback_among(keys[0] if fallback is None else fallback, keys)
        engine = _engine(engine)

        async with get_session() as session:
            found = await MetricRepository(session, tenant_id).resolve(metric)
            if found is None:
                raise LoopInvalidError(f"no metric named or with id {metric!r}")
            _resolve(engine, found)

            repo = LoopRepository(session, tenant_id)
            if key is None:
                base = _key_from(name, "loop")
                key = _unique(base, {*await repo.keys_from(base), *_RESERVED_LOOP_KEYS})
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
            people = await _owner(session, tenant_id, loop)
            loop_dict = loop_to_dict(loop, people)
            route = route_of(loop)
            change = await ChangeRepository(session, tenant_id).record(
                "loop.create", "loop", loop.id, actor, after=loop_dict, reason=reason
            )
        await self._routes.put(tenant_id, route)
        return Applied.of(loop_dict, change)

    async def launch_loop(
        self, tenant_id: str, ref: str, *, actor: Actor, reason: str | None = None
    ) -> Applied | None:
        async with get_session() as session:
            repo = LoopRepository(session, tenant_id)
            loop = await repo.resolve(ref)
            if loop is None:
                return None
            loop_key = loop.key
            if loop.state != "draft":
                raise _not_draft(loop_key, loop.state, "only a draft can be launched")
            resolved = _resolve(loop.engine, loop.metric, loop.context_schema)
            people = await _owner(session, tenant_id, loop)
            before = loop_to_dict(loop, people)
            _append_cycle(loop, loop.engine)
            loop.state = "live"
            loop.live_since = datetime.now(timezone.utc)
            try:
                loop = await repo.reload(loop)
            except IntegrityError as e:
                raise _not_draft(
                    loop_key, "live", "only a draft can be launched"
                ) from e
            loop_dict = loop_to_dict(loop, people)
            record = cycle_record(tenant_id, loop, loop.cycles[-1], resolved)
            route = route_of(loop)
            change = await ChangeRepository(session, tenant_id).record(
                "loop.launch",
                "loop",
                loop.id,
                actor,
                before=before,
                after=loop_dict,
                reason=reason,
            )
        await self._redis.set_experiment(tenant_id, record["id"], record)
        await self._routes.put(tenant_id, route)
        return Applied.of(loop_dict, change)

    async def rename_loop(
        self,
        tenant_id: str,
        ref: str,
        *,
        name: str | None = None,
        key: str | None = None,
        actor: Actor,
        reason: str | None = None,
        undoing: Undoing | None = None,
    ) -> Applied | None:
        """a new name at any time; a new key only while the loop is a draft."""
        if name is None and key is None:
            raise LoopInvalidError("a rename needs a new name, a new key or both")
        if name is not None:
            name = _name(name, "a loop")
        if key is not None:
            _check_loop_key(key)

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
            people = await _owner(session, tenant_id, loop)
            before = loop_to_dict(loop, people)
            old_key = loop.key
            if name is not None:
                loop.name = name
            if key is not None:
                loop.key = key
            try:
                loop = await repo.reload(loop)
            except IntegrityError as e:
                raise _taken(key) from e
            loop_dict = loop_to_dict(loop, people)
            route = route_of(loop)
            change = await ChangeRepository(session, tenant_id).record(
                "loop.rename",
                "loop",
                loop.id,
                actor,
                before=before,
                after=loop_dict,
                reason=reason,
                undoing=undoing,
            )
        await self._routes.put(tenant_id, route, old_key=old_key)
        return Applied.of(loop_dict, change)

    async def update_delivery(
        self,
        tenant_id: str,
        ref: str,
        *,
        audience: list[dict[str, Any]] | None = None,
        rollout: int | None = None,
        schedule: dict[str, Any] | None = None,
        fallback: str | None = None,
        actor: Actor,
        reason: str | None = None,
        undoing: Undoing | None = None,
    ) -> Applied | None:
        """who the loop decides for, and what everyone else gets. a part left
        out keeps its value; a part given replaces it whole."""
        async with get_session() as session:
            loop = await LoopRepository(session, tenant_id).resolve(ref)
            if loop is None:
                return None
            written = await self._write_delivery(
                session,
                tenant_id,
                loop,
                audience=audience,
                rollout=rollout,
                schedule=schedule,
                fallback=fallback,
                actor=actor,
                reason=reason,
                undoing=undoing,
            )
        return await self._publish(tenant_id, written)

    async def _write_delivery(
        self,
        session: AsyncSession,
        tenant_id: str,
        loop: Loop,
        *,
        audience: list[dict[str, Any]] | None,
        rollout: int | None,
        schedule: dict[str, Any] | None,
        fallback: str | None,
        actor: Actor,
        reason: str | None,
        undoing: Undoing | None = None,
    ) -> _Written:
        given = {
            name: value
            for name, value in (
                ("audience", audience),
                ("rollout", rollout),
                ("schedule", schedule),
            )
            if value is not None
        }
        if not given and fallback is None:
            raise LoopInvalidError(
                "a delivery change needs an audience, a rollout, a schedule, "
                "a fallback or several"
            )
        if loop.state == "retired":
            raise LoopRetiredError(
                f"its delivery can't change: the loop {loop.key!r} is retired; "
                f"{_DELIVERY_FIXES['retired']}"
            )
        current = delivery_of(loop.delivery)
        delivery = _delivery({**current.model_dump(mode="json"), **given})
        if fallback is not None:
            _fallback_among(fallback, [o.key for o in loop.options])
        else:
            fallback = loop.fallback_key
        if delivery == current and fallback == loop.fallback_key:
            raise LoopInvalidError(
                "nothing changes: the delivery and fallback are the loop's own"
            )
        people = await _owner(session, tenant_id, loop)
        before = loop_to_dict(loop, people)
        loop.delivery = delivery.model_dump(mode="json")
        loop.fallback_key = fallback
        loop = await LoopRepository(session, tenant_id).reload(loop)
        loop_dict = loop_to_dict(loop, people)
        change = await ChangeRepository(session, tenant_id).record(
            "delivery.update",
            "loop",
            loop.id,
            actor,
            before=before,
            after=loop_dict,
            reason=reason,
            undoing=undoing,
        )
        return _Written(loop_dict, change, route_of(loop), None)

    async def update_brief(
        self,
        tenant_id: str,
        ref: str,
        *,
        purpose: str | None = None,
        owner: str | None = None,
        options: list[dict[str, Any]] | None = None,
        engine: str | None = None,
        metric: str | None = None,
        fallback: str | None = None,
        actor: Actor,
        reason: str | None = None,
        undoing: Undoing | None = None,
    ) -> Applied | None:
        """the loop's purpose and owner, in any state. a draft's options,
        engine, metric and fallback too, since nothing on a draft starts a
        cycle; past draft those start a new cycle instead."""
        async with get_session() as session:
            loop = await LoopRepository(session, tenant_id).resolve(ref)
            if loop is None:
                return None
            written = await self._write_brief(
                session,
                tenant_id,
                loop,
                purpose=purpose,
                owner=owner,
                options=options,
                engine=engine,
                metric=metric,
                fallback=fallback,
                actor=actor,
                reason=reason,
                undoing=undoing,
            )
        return await self._publish(tenant_id, written)

    async def _write_brief(
        self,
        session: AsyncSession,
        tenant_id: str,
        loop: Loop,
        *,
        purpose: str | None,
        owner: str | None,
        options: list[dict[str, Any]] | None,
        engine: str | None,
        metric: str | None,
        fallback: str | None,
        actor: Actor,
        reason: str | None,
        undoing: Undoing | None = None,
    ) -> _Written:
        drafting = any(v is not None for v in (options, engine, metric, fallback))
        if purpose is None and owner is None and not drafting:
            raise LoopInvalidError(
                "a brief change needs a purpose or an owner, and on a draft it "
                "can also take options, an engine, a metric or a fallback"
            )
        if drafting and loop.state != "draft":
            raise LoopStateError(
                f"options, the engine and the metric change with a new cycle once "
                f"a loop is launched: the loop {loop.key!r} is {loop.state}; "
                f"start a new cycle instead"
            )
        built = _options(options) if options is not None else None
        engine = _engine(engine) if engine is not None else loop.engine
        found = await _metric(session, tenant_id, metric) if metric else loop.metric
        owner_id = await _member(session, tenant_id, owner) if owner else None
        if drafting:
            _resolve(engine, found, loop.context_schema)
            keys = [o.key for o in (built if built is not None else loop.options)]
            if fallback is not None:
                _fallback_among(fallback, keys)
            elif loop.fallback_key in keys:
                fallback = loop.fallback_key
            else:
                raise LoopInvalidError(
                    f"the fallback {loop.fallback_key!r} is not one of the new "
                    f"options; name one of them as the fallback ({', '.join(keys)})"
                )

        people = await People.load(
            session, tenant_id, [loop.owner_user_id, owner_id or ""]
        )
        before = loop_to_dict(loop, people)
        if purpose is not None:
            loop.purpose = purpose.strip()
        if owner_id is not None:
            loop.owner_user_id = owner_id
        if drafting:
            if built is not None:
                _replace_options(loop, built)
            loop.engine = engine
            loop.metric = found
            loop.fallback_key = fallback
        loop = await LoopRepository(session, tenant_id).reload(loop)
        loop_dict = loop_to_dict(loop, people)
        if _brief_of(loop_dict) == _brief_of(before):
            raise LoopInvalidError("nothing changes: the brief is the loop's own")
        change = await ChangeRepository(session, tenant_id).record(
            "brief.update",
            "loop",
            loop.id,
            actor,
            before=before,
            after=loop_dict,
            reason=reason,
            undoing=undoing,
        )
        return _Written(loop_dict, change, route_of(loop), None)

    async def update_context(
        self,
        tenant_id: str,
        ref: str,
        *,
        context: list[dict[str, Any]] | None,
        actor: Actor,
        reason: str | None = None,
        undoing: Undoing | None = None,
    ) -> Applied | None:
        """which context properties the loop's engine learns from; none
        clears it. on an engine that learns from context, a loop past draft
        starts a cycle with it, since what it learned no longer fits."""
        context = _context(context)
        async with get_session() as session:
            loop = await LoopRepository(session, tenant_id).resolve(ref)
            if loop is None:
                return None
            written = await self._write_context(
                session,
                tenant_id,
                loop,
                context=context,
                actor=actor,
                reason=reason,
                undoing=undoing,
            )
        return await self._publish(tenant_id, written)

    async def _write_context(
        self,
        session: AsyncSession,
        tenant_id: str,
        loop: Loop,
        *,
        context: list[dict[str, Any]] | None,
        actor: Actor,
        reason: str | None,
        undoing: Undoing | None = None,
    ) -> _Written:
        if loop.state == "retired":
            raise LoopRetiredError(
                f"its context can't change: the loop {loop.key!r} is retired; "
                f"{_DELIVERY_FIXES['retired']}"
            )
        _check_context(loop, context, loop.engine)
        if starts_cycle(loop.state, loop.engine):
            return await self._next_cycle(
                session,
                tenant_id,
                loop,
                "context.update",
                options=None,
                engine=None,
                metric=None,
                fallback=None,
                context=context,
                actor=actor,
                reason=reason,
            )
        people = await _owner(session, tenant_id, loop)
        before = loop_to_dict(loop, people)
        loop.context_schema = context
        loop = await LoopRepository(session, tenant_id).reload(loop)
        loop_dict = loop_to_dict(loop, people)
        change = await ChangeRepository(session, tenant_id).record(
            "context.update",
            "loop",
            loop.id,
            actor,
            before=before,
            after=loop_dict,
            reason=reason,
            undoing=undoing,
        )
        return _Written(loop_dict, change, route_of(loop), None)

    async def apply_edits(
        self,
        tenant_id: str,
        ref: str,
        edits: Edits,
        *,
        actor: Actor,
        reason: str | None = None,
        check: bool = False,
    ) -> Edited | None:
        """edits staged across a loop's tabs, in one transaction: one change
        per kind, and at most one new cycle carrying every edit that needs
        one. a refused part refuses them all. a check runs the same apply and
        keeps nothing, so it says exactly what the apply would do."""
        if edits.empty:
            raise LoopInvalidError(
                "an apply needs at least one edit: brief, cycle, delivery or context"
            )
        context = edits.context
        if context is not UNSET:
            with _part("context"):
                context = _context(context)
        try:
            async with get_session() as session:
                repo = LoopRepository(session, tenant_id)
                loop = await repo.resolve(ref)
                if loop is None:
                    return None
                steps = await self._apply(
                    session, tenant_id, loop, edits, context, actor, reason
                )
                written = [step for step, _ in steps]
                cycled = next((w for w in written if w.record is not None), None)
                edited = Edited(
                    loop=written[-1].loop,
                    changes=[_planned(w, parts, not check) for w, parts in steps],
                    cycle=cycled.loop["cycle"]["number"] if cycled else None,
                )
                if check:
                    raise Checked(edited)
        except Checked as checked:
            return checked.edited
        if cycled is not None:
            await self._redis.set_experiment(
                tenant_id, cycled.record["id"], cycled.record
            )
        await self._routes.put(tenant_id, written[-1].route)
        return edited

    async def _apply(
        self,
        session: AsyncSession,
        tenant_id: str,
        loop: Loop,
        edits: Edits,
        context: StagedContext,
        actor: Actor,
        reason: str | None,
    ) -> list[tuple[_Written, tuple[str, ...]]]:
        """the steps of an apply, in order. on a draft the cycle's edits are
        the brief's; past draft they start one cycle, which also takes the
        fallback, and the context when the new cycle's engine learns from it."""
        repo = LoopRepository(session, tenant_id)
        loop_id = loop.id
        brief, cycle, delivery = edits.brief, edits.cycle, edits.delivery
        fallback = delivery.fallback if delivery else None
        staged_context = context is not UNSET
        steps: list[tuple[_Written, tuple[str, ...]]] = []

        async def fresh() -> Loop:
            return await repo.get(loop_id)

        if loop.state == "draft":
            if staged_context:
                with _part("context"):
                    steps.append(
                        (
                            await self._write_context(
                                session,
                                tenant_id,
                                loop,
                                context=context,
                                actor=actor,
                                reason=reason,
                            ),
                            ("context",),
                        )
                    )
                loop = await fresh()
            if brief is not None or cycle is not None:
                parts = tuple(
                    name
                    for name, given in (
                        ("brief", brief is not None),
                        ("cycle", cycle is not None),
                        ("delivery", cycle is not None and fallback is not None),
                    )
                    if given
                )
                with _part(parts[0]):
                    steps.append(
                        (
                            await self._write_brief(
                                session,
                                tenant_id,
                                loop,
                                purpose=brief.purpose if brief else None,
                                owner=brief.owner if brief else None,
                                options=cycle.options if cycle else None,
                                engine=cycle.engine if cycle else None,
                                metric=cycle.metric if cycle else None,
                                fallback=fallback if cycle else None,
                                actor=actor,
                                reason=reason,
                            ),
                            parts,
                        )
                    )
                loop = await fresh()
                if cycle is not None:
                    fallback = None
        else:
            if brief is not None:
                with _part("brief"):
                    steps.append(
                        (
                            await self._write_brief(
                                session,
                                tenant_id,
                                loop,
                                purpose=brief.purpose,
                                owner=brief.owner,
                                options=None,
                                engine=None,
                                metric=None,
                                fallback=None,
                                actor=actor,
                                reason=reason,
                            ),
                            ("brief",),
                        )
                    )
                loop = await fresh()
            if cycle is not None:
                with _part("cycle"):
                    engine = _engine(cycle.engine) if cycle.engine else loop.engine
                rides = staged_context and _learns_from_context(engine)
                if rides:
                    with _part("context"):
                        _check_context(loop, context, engine)
                with _part("cycle"):
                    parts = ("cycle",)
                    if fallback is not None:
                        parts += ("delivery",)
                    if rides:
                        parts += ("context",)
                    steps.append(
                        (
                            await self._next_cycle(
                                session,
                                tenant_id,
                                loop,
                                "cycle.start",
                                options=(
                                    _options(cycle.options)
                                    if cycle.options is not None
                                    else None
                                ),
                                engine=engine,
                                metric=(
                                    await _metric(session, tenant_id, cycle.metric)
                                    if cycle.metric
                                    else None
                                ),
                                fallback=fallback,
                                context=context if rides else loop.context_schema,
                                actor=actor,
                                reason=reason,
                            ),
                            parts,
                        )
                    )
                loop = await fresh()
                fallback = None
                if rides:
                    staged_context = False
            if staged_context:
                with _part("context"):
                    steps.append(
                        (
                            await self._write_context(
                                session,
                                tenant_id,
                                loop,
                                context=context,
                                actor=actor,
                                reason=reason,
                            ),
                            ("context",),
                        )
                    )
                loop = await fresh()

        rode = (
            delivery is not None and delivery.fallback is not None and fallback is None
        )
        if delivery is not None and (delivery.placing or not rode):
            with _part("delivery"):
                steps.append(
                    (
                        await self._write_delivery(
                            session,
                            tenant_id,
                            loop,
                            audience=delivery.audience,
                            rollout=delivery.rollout,
                            schedule=delivery.schedule,
                            fallback=fallback,
                            actor=actor,
                            reason=reason,
                        ),
                        ("delivery",),
                    )
                )
        return steps

    async def _publish(self, tenant_id: str, written: _Written) -> Applied:
        if written.record is not None:
            await self._redis.set_experiment(
                tenant_id, written.record["id"], written.record
            )
        await self._routes.put(tenant_id, written.route)
        return Applied.of(written.loop, written.change)

    async def add_note(
        self, tenant_id: str, ref: str, *, text: str, actor: Actor
    ) -> Applied | None:
        """a note in the loop's history, in any state. it changes nothing
        select reads, and it stays: a correction is a new note."""
        text = text.strip()
        if not text:
            raise LoopInvalidError("a note needs some text")
        if len(text) > NOTE_MAX_LENGTH:
            raise LoopInvalidError(
                f"a note is at most {NOTE_MAX_LENGTH} characters, got {len(text)}"
            )
        async with get_session() as session:
            loop = await LoopRepository(session, tenant_id).resolve(ref)
            if loop is None:
                return None
            loop_dict = loop_to_dict(loop, await _owner(session, tenant_id, loop))
            change = await ChangeRepository(session, tenant_id).record(
                NOTE, "loop", loop.id, actor, after={"text": text}
            )
        return Applied.of(loop_dict, change)

    async def pause_loop(
        self,
        tenant_id: str,
        ref: str,
        *,
        actor: Actor,
        reason: str | None = None,
        evidence: dict | None = None,
        undoing: Undoing | None = None,
    ) -> Applied | None:
        """live or committed to paused: everyone gets the fallback until
        someone resumes it. a committed loop keeps its option for the resume,
        and decisions already made still seal and teach."""
        refused = "only a live or committed loop can be paused"
        return await self._transition(
            tenant_id,
            ref,
            "loop.pause",
            from_states=("live", "committed"),
            values={"state": "paused", "paused_from": Loop.state},
            refused=refused,
            actor=actor,
            reason=reason,
            evidence=evidence,
            undoing=undoing,
            check=_refusing(refused, _PAUSE_FIXES),
        )

    async def resume_loop(
        self,
        tenant_id: str,
        ref: str,
        *,
        actor: Actor,
        reason: str | None = None,
        undoing: Undoing | None = None,
    ) -> Applied | None:
        """back to the state the loop was paused from, deciding again from now."""
        return await self._transition(
            tenant_id,
            ref,
            "loop.resume",
            from_states=("paused",),
            values={
                "state": Loop.paused_from,
                "paused_from": None,
                "live_since": datetime.now(timezone.utc),
            },
            refused="only a paused loop can be resumed",
            actor=actor,
            reason=reason,
            evidence=None,
            undoing=undoing,
        )

    async def commit_loop(
        self,
        tenant_id: str,
        ref: str,
        *,
        option: str,
        actor: Actor,
        reason: str | None = None,
        undoing: Undoing | None = None,
    ) -> Applied | None:
        """live to committed: everyone gets one option of the current cycle,
        still as decisions, so its outcomes keep teaching it."""
        refused = "only a live loop can be committed"

        def check(loop: Loop) -> None:
            if loop.state != "live":
                return
            keys = [o["key"] for o in loop.cycles[-1].options]
            if option not in keys:
                raise LoopInvalidError(
                    f"{option!r} is not one of the loop's options ({', '.join(keys)})"
                )

        return await self._transition(
            tenant_id,
            ref,
            "loop.commit",
            from_states=("live",),
            values={"state": "committed", "committed_key": option},
            refused=refused,
            actor=actor,
            reason=reason,
            evidence=None,
            undoing=undoing,
            check=check,
        )

    async def reopen_loop(
        self,
        tenant_id: str,
        ref: str,
        *,
        actor: Actor,
        reason: str | None = None,
        undoing: Undoing | None = None,
    ) -> Applied | None:
        """committed back to live, in the same cycle with what it learned."""
        return await self._transition(
            tenant_id,
            ref,
            "loop.reopen",
            from_states=("committed",),
            values={"state": "live", "committed_key": None},
            refused="only a committed loop can be reopened",
            actor=actor,
            reason=reason,
            evidence=None,
            undoing=undoing,
        )

    async def retire_loop(
        self,
        tenant_id: str,
        ref: str,
        *,
        actor: Actor,
        reason: str | None = None,
    ) -> Applied | None:
        """live, committed or paused to retired: the choice has left the
        product. apps that still call it get the fallback; its cycle ends, and
        the decisions it already made keep sealing and teaching until their
        windows close."""
        refused = "only a live, committed or paused loop can be retired"
        return await self._transition(
            tenant_id,
            ref,
            "loop.retire",
            from_states=("live", "committed", "paused"),
            values={"state": "retired", "committed_key": None, "paused_from": None},
            refused=refused,
            actor=actor,
            reason=reason,
            evidence=None,
            undoing=None,
            check=_refusing(refused, _RETIRE_FIXES),
            end_cycle=True,
        )

    async def start_cycle(
        self,
        tenant_id: str,
        ref: str,
        *,
        options: list[dict[str, Any]] | None = None,
        engine: str | None = None,
        metric: str | None = None,
        context: StagedContext = UNSET,
        fallback: str | None = None,
        actor: Actor,
        reason: str | None = None,
    ) -> Applied | None:
        """new options, a new engine, a new metric or a new context, together
        in one new cycle that learns afresh. the fallback stays if its option
        does; otherwise it is named."""
        if options is None and engine is None and metric is None and context is UNSET:
            raise LoopInvalidError(
                "a new cycle needs new options, a new engine, a new metric or a "
                "new context; to learn afresh with the same ones, reset the cycle"
            )
        return await self._new_cycle(
            tenant_id,
            ref,
            "cycle.start",
            options=_options(options) if options is not None else None,
            engine=_engine(engine) if engine is not None else None,
            metric=metric,
            context=_context(context) if context is not UNSET else UNSET,
            fallback=fallback,
            actor=actor,
            reason=reason,
        )

    async def reset_cycle(
        self, tenant_id: str, ref: str, *, actor: Actor, reason: str | None = None
    ) -> Applied | None:
        """the same options, engine and fallback in a new cycle that learns
        afresh."""
        return await self._new_cycle(
            tenant_id,
            ref,
            "cycle.reset",
            options=None,
            engine=None,
            metric=None,
            context=UNSET,
            fallback=None,
            actor=actor,
            reason=reason,
        )

    async def _new_cycle(
        self,
        tenant_id: str,
        ref: str,
        kind: str,
        *,
        options: list[LoopOption] | None,
        engine: str | None,
        metric: str | None,
        context: StagedContext,
        fallback: str | None,
        actor: Actor,
        reason: str | None,
    ) -> Applied | None:
        """ends the current cycle and starts the next. the state stays, so a
        paused loop stays paused. the earlier cycle's record stays in redis:
        its open decisions keep sealing and teaching it, never the new one."""
        async with get_session() as session:
            loop = await LoopRepository(session, tenant_id).resolve(ref)
            if loop is None:
                return None
            written = await self._next_cycle(
                session,
                tenant_id,
                loop,
                kind,
                options=options,
                engine=engine,
                metric=await _metric(session, tenant_id, metric) if metric else None,
                fallback=fallback,
                context=loop.context_schema if context is UNSET else context,
                actor=actor,
                reason=reason,
            )
        return await self._publish(tenant_id, written)

    async def _next_cycle(
        self,
        session: AsyncSession,
        tenant_id: str,
        loop: Loop,
        kind: str,
        *,
        options: list[LoopOption] | None,
        engine: str | None,
        metric: Metric | None,
        fallback: str | None,
        context: list[dict[str, Any]] | None,
        actor: Actor,
        reason: str | None,
    ) -> _Written:
        """the next cycle, written in the caller's session; the caller puts
        its record and route once the session commits."""
        refused = "only a live or paused loop can start a new cycle"
        repo = LoopRepository(session, tenant_id)
        _cyclable(refused)(loop)
        loop_key = loop.key
        state = loop.state
        if state not in ("live", "paused"):
            raise _moved(loop_key, state, refused)

        engine = engine or loop.engine
        keys = [o.key for o in (options if options is not None else loop.options)]
        if fallback is not None:
            _fallback_among(fallback, keys)
        elif loop.fallback_key in keys:
            fallback = loop.fallback_key
        else:
            raise LoopInvalidError(
                f"the fallback {loop.fallback_key!r} is not one of the new "
                f"options; name one of them as the fallback ({', '.join(keys)})"
            )
        metric = metric or loop.metric
        if (
            kind == "cycle.start"
            and engine == loop.engine
            and (options is None or _same_options(loop.cycles[-1], options))
            and metric.id == loop.metric_id
            and context == loop.context_schema
        ):
            raise LoopInvalidError(
                "the options, engine, metric and context are the cycle's own; to "
                "learn afresh with them, reset the cycle"
            )
        resolved = _resolve(engine, metric, context)

        people = await _owner(session, tenant_id, loop)
        before = loop_to_dict(loop, people)
        if not await repo.transition(loop.id, from_state=state, state=state):
            loop = await repo.get(loop.id)
            raise _moved(loop_key, loop.state, refused)
        if options is not None:
            _replace_options(loop, options)
        loop.engine = engine
        loop.metric = metric
        loop.fallback_key = fallback
        loop.context_schema = context
        loop.cycles[-1].ended_at = datetime.now(timezone.utc)
        await session.flush()
        _append_cycle(loop, engine)
        try:
            loop = await repo.reload(loop)
        except IntegrityError as e:
            raise _moved(loop_key, state, refused) from e
        loop_dict = loop_to_dict(loop, people)
        record = cycle_record(tenant_id, loop, loop.cycles[-1], resolved)
        change = await ChangeRepository(session, tenant_id).record(
            kind,
            "loop",
            loop.id,
            actor,
            before=before,
            after=loop_dict,
            reason=reason,
        )
        return _Written(loop_dict, change, route_of(loop), record)

    async def _transition(
        self,
        tenant_id: str,
        ref: str,
        kind: str,
        *,
        from_states: tuple[str, ...],
        values: dict[str, Any],
        refused: str,
        actor: Actor,
        reason: str | None,
        evidence: dict | None,
        undoing: Undoing | None,
        check: Callable[[Loop], None] | None = None,
        end_cycle: bool = False,
    ) -> Applied | None:
        async with get_session() as session:
            repo = LoopRepository(session, tenant_id)
            loop = await repo.resolve(ref)
            if loop is None:
                return None
            if check is not None:
                check(loop)
            loop_key = loop.key
            if loop.state not in from_states:
                raise _moved(loop_key, loop.state, refused)
            people = await _owner(session, tenant_id, loop)
            before = loop_to_dict(loop, people)
            if not await repo.transition(loop.id, from_state=loop.state, **values):
                loop = await repo.get(loop.id)
                raise _moved(loop_key, loop.state, refused)
            if end_cycle:
                loop.cycles[-1].ended_at = datetime.now(timezone.utc)
                await session.flush()
            loop = await repo.get(loop.id)
            loop_dict = loop_to_dict(loop, people)
            route = route_of(loop)
            change = await ChangeRepository(session, tenant_id).record(
                kind,
                "loop",
                loop.id,
                actor,
                before=before,
                after=loop_dict,
                reason=reason,
                evidence=evidence,
                undoing=undoing,
            )
        await self._routes.put(tenant_id, route)
        return Applied.of(loop_dict, change)

    async def delete_loop(
        self,
        tenant_id: str,
        ref: str,
        *,
        actor: Actor,
        undoing: Undoing | None = None,
    ) -> bool:
        async with get_session() as session:
            repo = LoopRepository(session, tenant_id)
            loop = await repo.resolve(ref)
            if loop is None:
                return False
            if loop.state != "draft":
                raise _not_draft(loop.key, loop.state, "only a draft can be deleted")
            before = loop_to_dict(loop, await _owner(session, tenant_id, loop))
            loop_id = loop.id
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

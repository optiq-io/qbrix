from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Iterator
from contextlib import contextmanager
from difflib import get_close_matches

from proxysvc.core.error import ChangeConflictError
from proxysvc.core.error import ChangeMovedError
from proxysvc.core.error import ChangeNotUndoableError
from proxysvc.core.error import ExperimentLimitError
from proxysvc.core.error import ExperimentRunningError
from proxysvc.core.error import InvalidCursorError
from proxysvc.core.error import LoopInvalidError
from proxysvc.core.error import LoopKeyTakenError
from proxysvc.core.error import LoopStateError
from proxysvc.core.error import MetricInvalidError
from proxysvc.core.error import MetricNameTakenError


class Refusal(Exception):
    """a call qbrix refused, worded for the agent: what went wrong and the fix."""


def _sentence(message: str) -> str:
    message = message.strip()
    message = message[:1].upper() + message[1:]
    return message if message.endswith(".") else f"{message}."


def _did_you_mean(ref: str, known: Iterable[str]) -> str:
    close = get_close_matches(ref, sorted(known), n=1)
    return f" Did you mean {close[0]}?" if close else ""


def role(verb: str) -> Refusal:
    return Refusal(f"Your role can't {verb}. Ask an admin of this workspace.")


def unknown_loop(ref: str, keys: Iterable[str]) -> Refusal:
    hint = _did_you_mean(ref, keys) or " Call loops_list to see this workspace's loops."
    return Refusal(f"No loop with key or id {ref}.{hint}")


def unknown_metric(ref: str, names: Iterable[str]) -> Refusal:
    hint = (
        _did_you_mean(ref, names)
        or " Call metrics_list to see this workspace's metrics, or metric_create to add one."
    )
    return Refusal(f"No metric named or with id {ref}.{hint}")


def not_draft(key: str, state: str) -> Refusal:
    if state == "live":
        return Refusal(
            f"The loop {key} is live already; launching applies only to drafts."
        )
    return Refusal(
        f"The loop {key} is {state}; launching applies only to drafts. "
        f"Resume it in the console to serve it again."
    )


def no_cycle(key: str, number: int, last: int | None) -> Refusal:
    if last is None:
        return Refusal(
            f"The loop {key} is a draft and has no cycles yet. "
            f"Leave cycle out, or launch it with loop_launch first."
        )
    return Refusal(
        f"The loop {key} has no cycle {number}; its cycles are 1 to {last}. "
        f"Leave cycle out for the current one."
    )


def unknown_change(ref: str) -> Refusal:
    return Refusal(
        f"No change with id {ref}. Call changes_list to see this workspace's changes."
    )


@contextmanager
def undo_refusals() -> Iterator[None]:
    """why an undo was refused. nothing was applied in any of these."""
    try:
        yield
    except ChangeMovedError as e:
        raise Refusal(f"{_sentence(str(e))} Nothing was undone.") from e
    except ChangeNotUndoableError as e:
        raise Refusal(
            f"{_sentence(str(e))} Make a new change instead, if it is still needed."
        ) from e
    except ExperimentRunningError as e:
        raise Refusal(f"{_sentence(str(e))} Nothing was undone.") from e
    except (
        ChangeConflictError,
        ExperimentLimitError,
        LoopKeyTakenError,
        LoopStateError,
    ) as e:
        raise Refusal(f"{_sentence(str(e))} Nothing was undone.") from e


def too_many_changes(limit: int, retry_after: int) -> Refusal:
    return Refusal(
        f"This connection made {limit} changes this minute. "
        f"Try again in {retry_after} seconds; nothing was applied."
    )


def running() -> Refusal:
    return Refusal(
        "The same call is still running. Try again in a moment for its result."
    )


@contextmanager
def refusals() -> Iterator[None]:
    """the domain errors any tool can meet, each turned into its fix."""
    try:
        yield
    except InvalidCursorError as e:
        raise Refusal(
            "That cursor isn't one this tool gave out. "
            "Call again without cursor to start from the newest."
        ) from e
    except LoopKeyTakenError as e:
        raise Refusal(
            f"{_sentence(str(e))} Choose another key, or leave key out to "
            f"generate one from the name."
        ) from e
    except MetricNameTakenError as e:
        raise Refusal(
            f"{_sentence(str(e))} Use it as it is (metrics_list shows it), "
            f"or choose another name."
        ) from e
    except LoopInvalidError as e:
        raise Refusal(f"{_sentence(str(e))} Fix it and call again.") from e
    except MetricInvalidError as e:
        raise Refusal(f"{_sentence(str(e))} Fix it and call again.") from e

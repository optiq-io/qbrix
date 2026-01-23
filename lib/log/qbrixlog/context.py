from __future__ import annotations

import uuid
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Generator

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """get the current request id from context."""
    return _request_id.get()


def set_request_id(request_id: str | None) -> None:
    """set the request id in context."""
    _request_id.set(request_id)


def generate_request_id() -> str:
    """generate a new request id."""
    return uuid.uuid4().hex


@contextmanager
def request_context(request_id: str | None = None) -> Generator[str, None, None]:
    """context manager for request-scoped logging.

    if request_id is not provided, generates a new one.
    restores the previous request_id on exit.
    """
    previous = _request_id.get()
    new_id = request_id or generate_request_id()
    _request_id.set(new_id)
    try:
        yield new_id
    finally:
        _request_id.set(previous)

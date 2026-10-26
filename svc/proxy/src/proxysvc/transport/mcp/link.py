from __future__ import annotations

from typing import Literal
from urllib.parse import quote


def change_url(
    console_origin: str,
    target: Literal["loop", "metric"],
    ref: str,
    change_id: str,
) -> str:
    """where a person reads a change in the console: the loop's history, or
    the metric's page, opened at that change."""
    ref = quote(ref, safe="")
    if target == "loop":
        return f"{console_origin}/loops/{ref}/history?change={change_id}"
    return f"{console_origin}/metrics/{ref}?change={change_id}"

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from datetime import timezone

from qbrixstore.postgres.models import Mention

PULL_REQUEST = "pull_request"
COMMIT = "commit"

OPEN = "open"
MERGED = "merged"
CLOSED = "closed"

KEY_MAX = 64
_KEY = re.compile(r"[a-z0-9][a-z0-9_.-]*")
_QBRIX = re.compile(r"(?<![\w.-])qbrix:([a-z0-9][a-z0-9_.-]*)", re.IGNORECASE)
_SQUASHED = re.compile(r"\(#(\d+)\)\s*$")


def _key(raw: str) -> str | None:
    key = raw.lower().rstrip(".")
    if len(key) > KEY_MAX or not _KEY.fullmatch(key):
        return None
    return key


def _link(console_origin: str) -> re.Pattern:
    return re.compile(
        re.escape(console_origin.rstrip("/"))
        + r"(?:/next)?/loops/([a-z0-9][a-z0-9_.-]*)",
        re.IGNORECASE,
    )


def branch_keys(branch: str) -> list[str]:
    """the keys a branch names as qbrix/<key>, since a branch can't hold a colon."""
    segments = branch.split("/")
    found = []
    for segment, following in zip(segments, segments[1:]):
        if segment.lower() == "qbrix":
            key = _key(following)
            if key is not None:
                found.append(key)
    return found


def mentioned_keys(
    texts: Iterable[str | None], *, console_origin: str, branch: str | None = None
) -> list[str]:
    """the loop keys these texts name explicitly, in order and once each:
    qbrix:<key>, a link to the loop on this install's console, or qbrix/<key>
    in a branch. a bare key names nothing."""
    link = _link(console_origin)
    found: list[str] = []
    for text in texts:
        if not text:
            continue
        for pattern in (_QBRIX, link):
            for match in pattern.finditer(text):
                key = _key(match.group(1))
                if key is not None:
                    found.append(key)
    if branch:
        found += branch_keys(branch)
    return list(dict.fromkeys(found))


def squashed_number(message: str) -> int | None:
    """the pull request a squash merge's commit names at the end of its first
    line, as github writes it: "Title (#42)"."""
    match = _SQUASHED.search(message.split("\n", 1)[0])
    return int(match.group(1)) if match else None


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def mention_entry(mention: Mention) -> dict:
    """a mention as a loop's history reads it."""
    return {
        "type": "mention",
        "id": mention.id,
        "kind": mention.kind,
        "repository": mention.repository,
        "number": mention.number,
        "sha": mention.sha,
        "title": mention.title,
        "author": mention.author,
        "state": mention.state,
        "url": mention.url,
        "at": _iso(mention.at),
        "opened_at": _iso(mention.opened_at),
        "merged_at": _iso(mention.merged_at),
        "closed_at": _iso(mention.closed_at),
        "merged_by": mention.merged_by,
    }

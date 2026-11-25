from __future__ import annotations

from typing import Literal
from typing import NamedTuple

NOTE = "note.add"
NOTE_KINDS = frozenset({NOTE})
NOTE_MAX_LENGTH = 4000

HistoryShow = Literal["all", "changes", "notes", "github"]


class HistoryFilter(NamedTuple):
    """which of a loop's history one show reads: changes of these kinds, and
    whether pull requests and commits that mention it."""

    changes: bool
    kinds: frozenset[str]
    except_kinds: frozenset[str]
    mentions: bool


HISTORY_SHOW: dict[str, HistoryFilter] = {
    "all": HistoryFilter(True, frozenset(), frozenset(), True),
    "changes": HistoryFilter(True, frozenset(), NOTE_KINDS, False),
    "notes": HistoryFilter(True, NOTE_KINDS, frozenset(), False),
    "github": HistoryFilter(False, frozenset(), frozenset(), True),
}

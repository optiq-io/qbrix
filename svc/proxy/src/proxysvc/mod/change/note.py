from __future__ import annotations

from typing import Literal

NOTE = "note.add"
NOTE_KINDS = frozenset({NOTE})
NOTE_MAX_LENGTH = 4000

HistoryShow = Literal["all", "changes", "notes"]

HISTORY_SHOW: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "all": (frozenset(), frozenset()),
    "changes": (frozenset(), NOTE_KINDS),
    "notes": (NOTE_KINDS, frozenset()),
}

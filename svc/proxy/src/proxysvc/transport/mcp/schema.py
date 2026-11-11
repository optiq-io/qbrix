from __future__ import annotations

from typing import Any
from typing import Literal
from typing import Optional

from pydantic import BaseModel

from proxysvc.core.autonomy import Level
from proxysvc.transport.http.router.change import ChangeEntry
from proxysvc.transport.http.router.change import ChangePage
from proxysvc.transport.http.router.loop import HistoryEntry
from proxysvc.transport.http.router.loop import LoopResults
from proxysvc.transport.http.router.loop import LoopSummary
from proxysvc.transport.http.router.loop import ResultsResponse
from proxysvc.transport.http.router.loop import Share
from proxysvc.transport.http.router.loop import SeriesPoint
from proxysvc.transport.http.router.metric import MetricResponse

Detail = Literal["concise", "full"]


class Option(BaseModel):
    id: str
    key: str
    name: str
    config: Optional[dict[str, Any]] = None


class Loop(LoopSummary):
    options: list[Option]


class Wiring(BaseModel):
    python: str
    javascript: str


class LoopView(Loop):
    latest_change: Optional[HistoryEntry] = None
    wire: Wiring
    autonomy: dict[str, Level]
    declined: list[ChangeEntry]


class LoopListItem(Loop):
    latest_change: Optional[HistoryEntry] = None
    results: Optional[LoopResults] = None


class LoopPage(BaseModel):
    loops: list[LoopListItem]
    next_cursor: Optional[str] = None


class ShareView(Share):
    series: Optional[list[SeriesPoint]] = None


class ResultsView(ResultsResponse):
    share: Optional[ShareView] = None


class MetricLoop(BaseModel):
    id: str
    key: str
    name: str
    state: str


class MetricInUse(MetricResponse):
    loops: list[MetricLoop]


class MetricList(BaseModel):
    metrics: list[MetricInUse]


class ChangeRef(BaseModel):
    id: str
    kind: str
    undoable: bool
    url: str


ChangeStatus = Literal["applied", "waiting"]


class LoopChanged(BaseModel):
    """the loop as the change left it; while the change waits, as it is now,
    and none for a loop that waits to be created."""

    status: ChangeStatus
    change: ChangeRef
    loop: Optional[Loop] = None


class MetricChanged(BaseModel):
    status: ChangeStatus
    change: ChangeRef
    metric: Optional[MetricResponse] = None


class ChangeUndone(BaseModel):
    status: ChangeStatus
    change: ChangeRef
    undone: ChangeEntry


class HistoryPage(ChangePage):
    url: str


class NoteAdded(BaseModel):
    status: ChangeStatus
    change: ChangeRef
    note: ChangeEntry

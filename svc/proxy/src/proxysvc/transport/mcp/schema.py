from __future__ import annotations

from typing import Any
from typing import Literal
from typing import Optional

from pydantic import BaseModel

from proxysvc.transport.http.router.change import ChangeEntry
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


class LoopChanged(BaseModel):
    status: Literal["applied"]
    change: ChangeRef
    loop: Loop


class MetricChanged(BaseModel):
    status: Literal["applied"]
    change: ChangeRef
    metric: MetricResponse


class ChangeUndone(BaseModel):
    status: Literal["applied"]
    change: ChangeRef
    undone: ChangeEntry

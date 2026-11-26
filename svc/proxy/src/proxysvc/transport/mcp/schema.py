from __future__ import annotations

from typing import Annotated
from typing import Any
from typing import Literal
from typing import Optional
from typing import Union

from pydantic import BaseModel
from pydantic import Field

from proxysvc.core.autonomy import Level
from proxysvc.transport.http.router.change import ChangeEntry
from proxysvc.transport.http.router.loop import Alert
from proxysvc.transport.http.router.loop import HistoryEntry
from proxysvc.transport.http.router.loop import LoopResults
from proxysvc.transport.http.router.loop import MentionEntry
from proxysvc.transport.http.router.loop import LoopSummary
from proxysvc.transport.http.router.loop import OpenAlert
from proxysvc.transport.http.router.loop import PreviewResponse
from proxysvc.transport.http.router.loop import ResultsResponse
from proxysvc.transport.http.router.loop import Share
from proxysvc.transport.http.router.loop import SeriesPoint
from proxysvc.transport.http.router.metric import MetricCycleStarted
from proxysvc.transport.http.router.metric import MetricListHealthResponse
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
    alerts: list[Alert]
    recovered: list[Alert]
    wire: Wiring
    autonomy: dict[str, Level]
    declined: list[ChangeEntry]
    merged_pull_request: Optional[MentionEntry] = None


class LoopListItem(Loop):
    latest_change: Optional[HistoryEntry] = None
    alerts: list[OpenAlert] = []
    results: Optional[LoopResults] = None


class LoopPage(BaseModel):
    loops: list[LoopListItem]
    next_cursor: Optional[str] = None


class ShareView(Share):
    series: Optional[list[SeriesPoint]] = None


PreviewView = PreviewResponse


class ResultsView(ResultsResponse):
    share: Optional[ShareView] = None


class MetricLoop(BaseModel):
    id: str
    key: str
    name: str
    state: str


class MetricInUse(MetricResponse):
    loops: list[MetricLoop]
    health: MetricListHealthResponse


class MetricList(BaseModel):
    metrics: list[MetricInUse]


class ChangeRef(BaseModel):
    id: str
    kind: str
    undoable: bool
    url: str


ChangeStatus = Literal["applied", "waiting", "declined"]


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
    cycles: list[MetricCycleStarted] = []


class ChangeUndone(BaseModel):
    status: ChangeStatus
    change: ChangeRef
    undone: ChangeEntry


class ChangeView(ChangeEntry):
    url: str


class HistoryPage(BaseModel):
    entries: list[
        Annotated[Union[ChangeEntry, MentionEntry], Field(discriminator="type")]
    ]
    next_cursor: Optional[str] = None
    url: str


class NoteAdded(BaseModel):
    status: ChangeStatus
    change: ChangeRef
    note: ChangeEntry


class DocsSection(BaseModel):
    page: str
    page_title: str
    path: list[str]
    anchor: str
    url: str
    text: str


class DocsHeading(BaseModel):
    path: list[str]
    anchor: str
    url: str


class DocsAnswer(BaseModel):
    sections: list[DocsSection]
    truncated: bool
    outline: Optional[list[DocsHeading]] = None
    pages: Optional[list[str]] = None

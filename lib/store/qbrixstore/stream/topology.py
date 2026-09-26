from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Mapping

from qbrixstore.event import AuditEvent
from qbrixstore.event import Event
from qbrixstore.event import FeedbackEvent
from qbrixstore.event import SelectionEvent

# a group that is not listed on its stream's spec cannot be joined, so the
# registry below is the complete set of consumers in the system.

DEFAULT_MAX_LEN = 1_000_000

# a newly created group starts here unless its stream overrides it: "0" drains
# whatever history the stream still holds. only applies at group creation; an
# existing group keeps its own position.
DEFAULT_START_ID = "0"


# eq=False: registry entries are singletons, so identity is the right identity,
# and it keeps the spec hashable despite carrying a mapping.
@dataclass(frozen=True, eq=False)
class StreamSpec:
    """the shape of one redis stream: who writes it, who reads it, how it trims.

    this is the single declaration of a stream's topology. the properties that
    have to hold across *all* of a stream's consumers — above all whether an ack
    may delete the entry — are derived here rather than passed at each call
    site, because no single call site can know what the others do.
    """

    name: str
    event: type[Event]
    groups: frozenset[str]
    max_len: int = DEFAULT_MAX_LEN
    start_ids: Mapping[str, str] = field(default_factory=dict)
    delete_on_ack_override: bool | None = None

    def __post_init__(self) -> None:
        if not self.groups:
            raise ValueError(f"{self.name}: a stream needs at least one group")
        unknown = set(self.start_ids) - self.groups
        if unknown:
            raise ValueError(f"{self.name}: start_ids for undeclared groups {unknown}")

    @property
    def delete_on_ack(self) -> bool:
        """whether acking an entry may also delete it.

        xdel removes the entry for *every* consumer group, so it is only safe
        when this stream has exactly one. adding a second group to `groups`
        flips this for all existing consumers with no call-site change — which
        is the entire reason topology is declared in one place.
        """
        if self.delete_on_ack_override is not None:
            return self.delete_on_ack_override
        return len(self.groups) == 1

    def start_id(self, group: str) -> str:
        return self.start_ids.get(group, DEFAULT_START_ID)

    def require_group(self, group: str) -> None:
        if group not in self.groups:
            raise ValueError(
                f"{group!r} is not a declared consumer group of {self.name!r} "
                f"(declared: {sorted(self.groups)})"
            )


FEEDBACK = StreamSpec(
    name="qbrix:feedback",
    event=FeedbackEvent,
    groups=frozenset({"cortex", "trace"}),
    # fanned out, so this should derive to False. pinned True until the stream
    # has the MAXLEN sizing that the flip requires.
    delete_on_ack_override=True,
)

SELECTION = StreamSpec(
    name="qbrix:selection",
    event=SelectionEvent,
    groups=frozenset({"trace", "metering"}),
    # a fresh metering group starts at the tail: pre-subscription backlog is
    # unbillable, and stripe rejects events >35 days old, which would wedge the
    # ack-after-emit consumer.
    start_ids={"metering": "$"},
)

AUDIT = StreamSpec(
    name="qbrix:audit",
    event=AuditEvent,
    groups=frozenset({"trace"}),
)

ALL: tuple[StreamSpec, ...] = (FEEDBACK, SELECTION, AUDIT)

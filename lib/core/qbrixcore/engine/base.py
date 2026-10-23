from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from types import MappingProxyType
from typing import Any
from typing import ClassVar
from typing import Mapping

from qbrixcore.engine.metric import MetricType
from qbrixcore.engine.metric import ScoreRange
from qbrixcore.engine.spec import EngineError
from qbrixcore.engine.spec import EngineVersion
from qbrixcore.policy.base import BasePolicy


@dataclass(frozen=True)
class Resolved:
    """the one policy and fixed params an engine runs for a cycle."""

    policy_cls: type[BasePolicy]
    fixed_params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(
            self, "fixed_params", MappingProxyType(dict(self.fixed_params))
        )


class BaseEngine(ABC):
    """chooses an option on every request; resolves its method from the metric type.

    engines take no settings: what a person could tune is pinned in each
    engine's resolution, so a version always means the same behaviour.
    """

    name: ClassVar[str]
    version: ClassVar[EngineVersion]
    needs_context: ClassVar[bool] = False

    @classmethod
    def resolve(
        cls,
        metric_type: MetricType,
        *,
        score_range: ScoreRange | None = None,
        context_dim: int | None = None,
        settings: Mapping[str, Any] | None = None,
    ) -> Resolved:
        try:
            metric_type = MetricType(metric_type)
        except ValueError as e:
            raise EngineError(f"unknown metric type {metric_type!r}") from e
        if settings:
            raise EngineError(
                f"engines take no settings, got {sorted(settings)} for {cls.name}"
            )
        if metric_type is MetricType.SCORE and score_range is None:
            raise EngineError("a score metric needs its declared range")
        if metric_type is not MetricType.SCORE and score_range is not None:
            raise EngineError(f"a {metric_type.value} metric has no range")
        if cls.needs_context and context_dim is None:
            raise EngineError(
                f"{cls.name} learns from context; declare a context schema"
            )
        return cls._resolve(metric_type, score_range, context_dim)

    @classmethod
    @abstractmethod
    def _resolve(
        cls,
        metric_type: MetricType,
        score_range: ScoreRange | None,
        context_dim: int | None,
    ) -> Resolved:
        pass

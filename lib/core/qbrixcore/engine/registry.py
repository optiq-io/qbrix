from __future__ import annotations

from typing import Iterable

from qbrixcore.engine.base import BaseEngine
from qbrixcore.engine.spec import ACCEPTED_FORMS
from qbrixcore.engine.spec import EngineError
from qbrixcore.engine.spec import EngineSpec


class EngineRegistry:
    """every engine version qbrix ships, keyed by name and major."""

    DEFAULT = "spinoza"

    def __init__(self, engines: Iterable[type[BaseEngine]]):
        self._majors: dict[str, dict[int, list[type[BaseEngine]]]] = {}
        seen = set()
        for engine in engines:
            key = (engine.name, engine.version)
            if key in seen:
                raise ValueError(f"{engine.name} {engine.version} is registered twice")
            seen.add(key)
            self._majors.setdefault(engine.name, {}).setdefault(
                engine.version.major, []
            ).append(engine)
        for majors in self._majors.values():
            for minors in majors.values():
                minors.sort(key=lambda e: e.version)

    @property
    def names(self) -> list[str]:
        return sorted(self._majors)

    def get(self, spec: str | EngineSpec) -> type[BaseEngine]:
        """the exact engine version a spec runs today."""
        spec = self._parse(spec)
        majors = self._majors.get(spec.name)
        if majors is None:
            raise EngineError(
                f"unknown engine {spec.name!r}; engines are "
                f"{', '.join(self.names)}, accepted forms: {ACCEPTED_FORMS}"
            )
        major = max(majors) if spec.major is None else spec.major
        minors = majors.get(major)
        if minors is None:
            raise EngineError(
                f"{spec.name} has no major {major}; available: "
                f"{', '.join(f'{spec.name}:{m}' for m in sorted(majors))}, "
                f"accepted forms: {ACCEPTED_FORMS}"
            )
        if spec.minor is None:
            return minors[-1]
        for engine in minors:
            if engine.version.minor == spec.minor:
                return engine
        raise EngineError(
            f"{spec.name} {major} has no minor {spec.minor}; available: "
            f"{', '.join(f'{spec.name}:{e.version}' for e in minors)}, "
            f"accepted forms: {ACCEPTED_FORMS}"
        )

    def pin(self, spec: str | EngineSpec) -> EngineSpec:
        """the spec a cycle keeps: a major that follows its minors, or an exact minor."""
        spec = self._parse(spec)
        engine = self.get(spec)
        return EngineSpec(engine.name, engine.version.major, spec.minor)

    @staticmethod
    def _parse(spec: str | EngineSpec) -> EngineSpec:
        return spec if isinstance(spec, EngineSpec) else EngineSpec.parse(spec)

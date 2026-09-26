from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PolicyParam:
    name: str
    type: str
    required: bool
    default: Any
    description: str
    constraints: dict[str, float]

from qbrixcore.engine.base import BaseEngine
from qbrixcore.engine.base import Resolved
from qbrixcore.engine.buridan import Buridan
from qbrixcore.engine.leibniz import Leibniz
from qbrixcore.engine.metric import MetricType
from qbrixcore.engine.metric import ScoreRange
from qbrixcore.engine.registry import EngineRegistry
from qbrixcore.engine.spec import EngineError
from qbrixcore.engine.spec import EngineSpec
from qbrixcore.engine.spec import EngineVersion
from qbrixcore.engine.spinoza import Spinoza

ENGINES = EngineRegistry([Spinoza, Leibniz, Buridan])

__all__ = [
    "BaseEngine",
    "Resolved",
    "MetricType",
    "ScoreRange",
    "EngineError",
    "EngineSpec",
    "EngineVersion",
    "EngineRegistry",
    "Spinoza",
    "Leibniz",
    "Buridan",
    "ENGINES",
]

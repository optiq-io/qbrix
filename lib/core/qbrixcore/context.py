import uuid
from dataclasses import dataclass, field
import numpy as np


@dataclass
class Context:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    vector: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float16))
    metadata: dict = field(default_factory=dict)

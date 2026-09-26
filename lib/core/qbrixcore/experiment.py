from dataclasses import dataclass, field
import uuid


@dataclass
class Experiment:
    name: str
    id: str = field(default_factory=lambda: str(uuid.uuid4().hex))

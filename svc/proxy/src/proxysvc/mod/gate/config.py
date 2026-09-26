from typing import List

from pydantic import Field

from .model.base import BaseConfig
from .model.experiment import ExperimentConfig
from .model.rule import Rule
from .model.base import BaseArmModel  # noqa


class FeatureGateConfig(BaseConfig):
    enabled: bool = Field(
        default=True, description="Whether the feature gate is enabled"
    )
    experiment: ExperimentConfig
    rules: List[Rule]

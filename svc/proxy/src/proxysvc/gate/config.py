from typing import List

from .model.base import BaseConfig
from .model.experiment import ExperimentConfig
from .model.rule import Rule
from .model.base import BaseArmModel  # noqa


class FeatureGateConfig(BaseConfig):
    experiment: ExperimentConfig
    rules: List[Rule]

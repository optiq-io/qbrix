from typing import List

from optiqgate.model.base import BaseConfig
from optiqgate.model.experiment import ExperimentConfig
from optiqgate.model.rule import Rule
from optiqgate.model.base import BaseArmModel  # noqa


class FeatureGateConfig(BaseConfig):
    experiment: ExperimentConfig
    rules: List[Rule]

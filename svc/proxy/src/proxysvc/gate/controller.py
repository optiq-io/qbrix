from enum import Flag, auto
from pydantic import BaseModel
from optiqgate.config import FeatureGateConfig, Rule, BaseArmModel


class ExperimentFlagState(Flag):
    """Flags representing the state of an experiment.

    Attributes
    ----------
    ENABLED : Flag
        Experiment is enabled
    ACTIVE : Flag
        Experiment is within active schedule
    BLACKOUT : Flag
        Experiment is outside active schedule
    DISABLED : Flag
        Experiment is disabled
    RPOS : Flag
        Context is within rollout percentage (positive)
    RNEG : Flag
        Context is outside rollout percentage (negative)
    """
    ENABLED = auto()
    ACTIVE = auto()
    BLACKOUT = auto()
    DISABLED = auto()
    RPOS = auto()
    RNEG = auto()


class FeatureGate:
    """Feature gate controller for experiment-based decision making.

    Attributes
    ----------
    negset : ExperimentFlagState
        Combination of flags that result in returning the committed arm
    """

    negset = ExperimentFlagState.DISABLED | ExperimentFlagState.BLACKOUT | ExperimentFlagState.RNEG  # noqa

    @classmethod
    def render_feature_flags(cls, config: FeatureGateConfig, input_model: BaseModel) -> ExperimentFlagState:
        """Render experiment state flags based on configuration and input.

        Parameters
        ----------
        config : FeatureGateConfig
            Feature gate configuration containing experiment settings
        input_model : BaseModel
            Input model with context attribute containing an id field

        Returns
        -------
        ExperimentFlagState
            Combined flags representing the current experiment state

        Notes
        -----
        Expects input_model to have:
        - context.id: str - Unique identifier for rollout calculation
        """
        experiment = config.experiment
        state = ExperimentFlagState(0)

        if experiment.enabled:
            state |= ExperimentFlagState.ENABLED
        else:
            state |= ExperimentFlagState.DISABLED
        if experiment.schedule.is_in_active_schedule():
            state |= ExperimentFlagState.ACTIVE
        else:
            state |= ExperimentFlagState.BLACKOUT
        if experiment.rollout.is_in_rollout(input_model.context.id):
            state |= ExperimentFlagState.RPOS
        else:
            state |= ExperimentFlagState.RNEG
        return state

    @classmethod
    def render_rules(cls, config: FeatureGateConfig, input_model: BaseModel) -> Rule | None:
        """Apply rules to input metadata and return first matching rule.

        Parameters
        ----------
        config : FeatureGateConfig
            Feature gate configuration containing rules
        input_model : BaseModel
            Input model with metadata attribute containing a dict

        Returns
        -------
        Rule | None
            First rule that matches the input metadata, or None if no match

        Notes
        -----
        Expects input_model to have:
        - metadata: dict - Dictionary to evaluate rules against
        """
        if not (rules := config.rules):
            return None

        for rule in rules:
            if rule.eval(input_model.metadata):
                return rule

        return None

    @classmethod
    def control(cls, config: FeatureGateConfig, input_model: BaseModel) -> BaseArmModel | None:
        """Determine which arm to return based on experiment state and rules.

        Parameters
        ----------
        config : FeatureGateConfig
            Feature gate configuration
        input_model : BaseModel
            Input model containing context and metadata

        Returns
        -------
        BaseArmModel | None
            Arm to commit based on evaluation, or None if no arm should be returned

        Raises
        ------
        AttributeError
            If input_model is missing required context.id or metadata attributes

        Notes
        -----
        Expects input_model to have:
        - context.id: str - Unique identifier for rollout calculation
        - metadata: dict - Dictionary to evaluate rules against

        Logic flow:
        1. Render feature flags based on experiment state
        2. If negset flags are present, return committed arm
        3. Otherwise, evaluate rules and return matching rule's arm
        4. If no rules match, return None
        """
        if not hasattr(input_model, 'context') or not hasattr(input_model.context, 'id'):
            raise AttributeError("input_model must have context.id attribute")

        if not hasattr(input_model, 'metadata'):
            raise AttributeError("input_model must have metadata attribute")

        fstate = cls.render_feature_flags(config, input_model)
        if cls.negset & fstate:
            return config.experiment.arm.committed

        if rule := cls.render_rules(config, input_model):
            return rule.arm.committed

        return None

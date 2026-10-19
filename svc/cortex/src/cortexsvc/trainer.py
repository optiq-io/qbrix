from __future__ import annotations

import numpy as np

from qbrixcore.context import Context
from qbrixcore.policy import BasePolicy
from qbrixlog import get_logger
from qbrixstore.event import FeedbackEvent
from qbrixstore.redis.client import Learning
from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.streams import RedisStreamConsumer

logger = get_logger(__name__)


def _build_policy_map() -> dict[str, type[BasePolicy]]:
    registry = {}

    def collect(cls):
        for subclass in cls.__subclasses__():
            if hasattr(subclass, "name") and subclass.name:
                registry[subclass.name] = subclass
            collect(subclass)

    collect(BasePolicy)
    return registry


POLICY_MAP = _build_policy_map()


class BatchTrainer:

    def __init__(self, redis_client: RedisClient, consumer: RedisStreamConsumer):
        self._redis = redis_client
        self._consumer = consumer

    async def train_experiment(
        self,
        tenant_id: str,
        experiment_id: str,
        messages: list[tuple[str, FeedbackEvent]],
    ) -> int:
        """train on a batch and ack it in the same transaction.

        returns how many outcomes were learned from. entries the learning
        already includes, and batches for a missing, paused or unknown-policy
        experiment, are acked without training.
        """
        message_ids = [message_id for message_id, _ in messages]
        trained = 0

        def train(experiment: dict | None, current: Learning) -> Learning | None:
            nonlocal trained
            trained = 0

            if experiment is None or not experiment.get("enabled", True):
                return None
            policy_cls = POLICY_MAP.get(experiment["policy"])
            if policy_cls is None:
                return None

            fresh = [(mid, ev) for mid, ev in messages if not current.includes(mid)]
            if len(fresh) < len(messages):
                logger.info(
                    "%s/%s: %d entries already applied, acking without training",
                    tenant_id,
                    experiment_id,
                    len(messages) - len(fresh),
                )
            if not fresh:
                return None

            if current.params is None:
                param_state = policy_cls.build_state(
                    num_arms=len(experiment["pool"]["arms"]),
                    **experiment.get("policy_params", {}),
                )
            else:
                param_state = policy_cls.param_state_cls.model_validate(current.params)

            for _, event in fresh:
                context = Context(
                    id=event.context_id,
                    vector=np.array(event.context_vector, dtype=np.float16),
                    metadata=event.context_metadata,
                )
                param_state = policy_cls.train(
                    ps=param_state,
                    context=context,
                    choice=event.arm_index,
                    reward=event.reward,
                )

            trained = len(fresh)
            return current.advance(param_state.model_dump(), [mid for mid, _ in fresh])

        await self._redis.apply_learning(
            tenant_id,
            experiment_id,
            train,
            lambda pipe: self._consumer.stage_ack(pipe, message_ids),
        )
        return trained

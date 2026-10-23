from __future__ import annotations

import numpy as np
from redis.asyncio.client import Pipeline

from qbrixcore.context import Context
from qbrixcore.policy import BasePolicy
from qbrixlog import get_logger
from qbrixstore.event import FeedbackEvent
from qbrixstore.redis import OutcomeDisposition
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
    ) -> dict[OutcomeDisposition, int]:
        """train on a batch and ack it in the same transaction, with the
        outcome counts.

        returns how the batch's new entries ended: learned from, or not and
        why. entries the learning already includes were counted when they were
        applied, so they are acked without training or counting.
        """
        message_ids = [message_id for message_id, _ in messages]
        last_arrival_ms = max(
            (event.timestamp_ms for _, event in messages), default=None
        )
        counts: dict[OutcomeDisposition, int] = {}

        def train(experiment: dict | None, current: Learning) -> Learning | None:
            nonlocal counts
            counts = {}

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

            if experiment is None:
                counts = {OutcomeDisposition.UNKNOWN_EXPERIMENT: len(fresh)}
                return None
            if not experiment.get("enabled", True):
                counts = {OutcomeDisposition.PAUSED: len(fresh)}
                return None
            policy_cls = POLICY_MAP.get(experiment["policy"])
            if policy_cls is None:
                counts = {OutcomeDisposition.UNKNOWN_POLICY: len(fresh)}
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

            counts = {OutcomeDisposition.LEARNED: len(fresh)}
            return current.advance(param_state.model_dump(), [mid for mid, _ in fresh])

        def ack(pipe: Pipeline) -> None:
            self._consumer.stage_ack(pipe, message_ids)
            self._redis.stage_outcomes(
                pipe, tenant_id, experiment_id, counts, last_arrival_ms
            )

        await self._redis.apply_learning(tenant_id, experiment_id, train, ack)
        return counts

    async def count_train_error(
        self, tenant_id: str, experiment_id: str, count: int
    ) -> None:
        await self._redis.count_outcomes(
            tenant_id, experiment_id, {OutcomeDisposition.TRAIN_ERROR: count}
        )

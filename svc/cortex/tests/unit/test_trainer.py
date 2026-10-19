import fakeredis
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from redis.asyncio.client import Pipeline

from qbrixcore.policy import POLICIES
from cortexsvc.trainer import BatchTrainer
from cortexsvc.trainer import POLICY_MAP
from cortexsvc.trainer import _build_policy_map
from qbrixstore.event import FeedbackEvent
from qbrixstore.redis.client import Learning
from qbrixstore.redis.client import RedisClient
from qbrixstore.redis.streams import RedisStreamConsumer
from qbrixstore.redis.streams import RedisStreamPublisher
from qbrixstore.stream import topology

EXPERIMENT = "exp-001"


class TestPolicyMapBuilding:
    """test policy registry construction."""

    def test_policy_map_covers_all_known_policies(self):
        # guards against the import regression where trainer.py imports only
        # qbrixcore.policy.base instead of the package, leaving POLICY_MAP empty
        expected = {cls.name for cls in POLICIES if cls.name}
        assert expected == set(POLICY_MAP.keys())

    def test_build_policy_map_returns_dict(self):
        policy_map = _build_policy_map()

        assert isinstance(policy_map, dict)
        assert len(policy_map) > 0

    def test_policy_map_contains_beta_ts(self):
        assert "BetaTSPolicy" in POLICY_MAP
        assert POLICY_MAP["BetaTSPolicy"].name == "BetaTSPolicy"

    def test_policy_map_contains_ucb1_tuned(self):
        assert "UCB1TunedPolicy" in POLICY_MAP
        assert POLICY_MAP["UCB1TunedPolicy"].name == "UCB1TunedPolicy"


@pytest.fixture
def redis_server(monkeypatch) -> fakeredis.FakeServer:
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        "redis.asyncio.from_url",
        lambda *_a, **_k: FakeRedis(server=server, decode_responses=True),
    )
    return server


@pytest.fixture
def control(redis_server) -> FakeRedis:
    return FakeRedis(server=redis_server, decode_responses=True)


@pytest_asyncio.fixture
async def store(redis_server):
    client = RedisClient()
    await client.connect()
    yield client
    await client.close()


@pytest_asyncio.fixture
async def consumer(redis_server):
    consumer = RedisStreamConsumer(topology.FEEDBACK, "cortex")
    await consumer.connect()
    await consumer.ensure_group()
    yield consumer
    await consumer.close()


@pytest.fixture
def trainer(store, consumer) -> BatchTrainer:
    return BatchTrainer(store, consumer)


@pytest_asyncio.fixture
async def experiment(store, tenant_id, sample_experiment_record):
    await store.set_experiment(tenant_id, EXPERIMENT, sample_experiment_record)
    return sample_experiment_record


def feedback(tenant_id: str, arm_index: int = 0, reward: float = 1.0) -> FeedbackEvent:
    return FeedbackEvent(
        tenant_id=tenant_id,
        experiment_id=EXPERIMENT,
        request_id="req",
        arm_index=arm_index,
        reward=reward,
        context_id="ctx",
        context_vector=[0.5, 0.3, 0.2],
        context_metadata={},
        timestamp_ms=1234567890,
    )


async def deliver(consumer, events: list[FeedbackEvent]):
    """publish and read back, so the entries sit in the group's PEL."""
    publisher = RedisStreamPublisher(topology.FEEDBACK)
    await publisher.connect()
    for event in events:
        await publisher.publish(event)
    await publisher.close()
    entries = await consumer.consume(batch_size=len(events), block_ms=0)
    return [(mid, FeedbackEvent.from_dict(data)) for mid, data in entries]


async def pending(control) -> int:
    return (await control.xpending(topology.FEEDBACK.name, "cortex"))["pending"]


@pytest.mark.asyncio
class TestTrainExperiment:

    async def test_learning_grows_by_the_batch_and_the_batch_is_acked(
        self, trainer, store, consumer, control, tenant_id, experiment
    ):
        messages = await deliver(
            consumer, [feedback(tenant_id), feedback(tenant_id, 1, 0.0)]
        )

        count = await trainer.train_experiment(tenant_id, EXPERIMENT, messages)

        assert count == 2
        learning = await store.read_learning(tenant_id, EXPERIMENT)
        assert learning.applied == 2
        assert learning.last_id == messages[-1][0]
        assert learning.params["alpha"] == [2.0, 1.0, 1.0]
        assert learning.params["beta"] == [1.0, 2.0, 1.0]
        assert await pending(control) == 0

    async def test_applied_accumulates_across_batches(
        self, trainer, store, consumer, tenant_id, experiment
    ):
        await trainer.train_experiment(
            tenant_id, EXPERIMENT, await deliver(consumer, [feedback(tenant_id)])
        )
        second = await deliver(consumer, [feedback(tenant_id), feedback(tenant_id)])
        await trainer.train_experiment(tenant_id, EXPERIMENT, second)

        learning = await store.read_learning(tenant_id, EXPERIMENT)
        assert learning.applied == 3
        assert learning.last_id == second[-1][0]

    async def test_a_fault_at_the_write_changes_nothing_and_redelivery_applies_once(
        self, trainer, store, consumer, control, tenant_id, experiment, monkeypatch
    ):
        messages = await deliver(
            consumer, [feedback(tenant_id), feedback(tenant_id, 2, 1.0)]
        )
        execute = Pipeline.execute

        async def crash(self, *args, **kwargs):
            raise ConnectionError("cortex lost redis at exec")

        monkeypatch.setattr(Pipeline, "execute", crash)
        with pytest.raises(ConnectionError):
            await trainer.train_experiment(tenant_id, EXPERIMENT, messages)
        monkeypatch.setattr(Pipeline, "execute", execute)

        assert await store.read_learning(tenant_id, EXPERIMENT) == Learning(params=None)
        assert await pending(control) == 2

        _, redelivered = await consumer.claim_pending(count=10)
        assert [mid for mid, _ in redelivered] == [mid for mid, _ in messages]
        await trainer.train_experiment(
            tenant_id,
            EXPERIMENT,
            [(mid, FeedbackEvent.from_dict(data)) for mid, data in redelivered],
        )

        learning = await store.read_learning(tenant_id, EXPERIMENT)
        assert learning.applied == 2
        assert learning.params["alpha"] == [2.0, 1.0, 2.0]
        assert await pending(control) == 0

    async def test_a_batch_redelivered_after_its_write_is_acked_not_trained(
        self, trainer, store, consumer, control, tenant_id, experiment
    ):
        """the write landed but its reply was lost: the entries are still pending."""
        messages = await deliver(consumer, [feedback(tenant_id), feedback(tenant_id)])
        applied = Learning(params=None).advance(
            {
                "num_arms": 3,
                "alpha": [3.0, 1.0, 1.0],
                "beta": [1.0, 1.0, 1.0],
                "T": [2, 0, 0],
            },
            [mid for mid, _ in messages],
        )
        await control.set(store._param_key(tenant_id, EXPERIMENT), '{"marker": 1}')
        await control.set(
            store._learning_key(tenant_id, EXPERIMENT), applied.encode_record()
        )

        count = await trainer.train_experiment(tenant_id, EXPERIMENT, messages)

        assert count == 0
        learning = await store.read_learning(tenant_id, EXPERIMENT)
        assert learning.params == {"marker": 1}
        assert learning.applied == 2
        assert await pending(control) == 0

    async def test_only_the_unapplied_tail_of_a_batch_trains(
        self, trainer, store, consumer, tenant_id, experiment
    ):
        first = await deliver(consumer, [feedback(tenant_id)])
        await trainer.train_experiment(tenant_id, EXPERIMENT, first)
        rest = await deliver(consumer, [feedback(tenant_id)])

        count = await trainer.train_experiment(tenant_id, EXPERIMENT, first + rest)

        assert count == 1
        learning = await store.read_learning(tenant_id, EXPERIMENT)
        assert learning.applied == 2
        assert learning.params["alpha"][0] == 3.0

    @pytest.mark.parametrize(
        "record",
        [
            None,
            {"policy": "unknown_policy", "pool": {"arms": [{"id": "a", "index": 0}]}},
            {"enabled": False},
        ],
        ids=["missing", "unknown-policy", "paused"],
    )
    async def test_acks_without_learning_when_the_experiment_cannot_learn(
        self,
        trainer,
        store,
        consumer,
        control,
        tenant_id,
        sample_experiment_record,
        record,
    ):
        if record is not None:
            await store.set_experiment(
                tenant_id, EXPERIMENT, {**sample_experiment_record, **record}
            )
        messages = await deliver(consumer, [feedback(tenant_id)])

        count = await trainer.train_experiment(tenant_id, EXPERIMENT, messages)

        assert count == 0
        assert await store.read_learning(tenant_id, EXPERIMENT) == Learning(params=None)
        assert await pending(control) == 0

    async def test_trains_when_explicitly_enabled(
        self, trainer, store, consumer, tenant_id, sample_experiment_record
    ):
        await store.set_experiment(
            tenant_id, EXPERIMENT, {**sample_experiment_record, "enabled": True}
        )
        messages = await deliver(consumer, [feedback(tenant_id)])

        assert await trainer.train_experiment(tenant_id, EXPERIMENT, messages) == 1

    async def test_initializes_params_from_policy_params(
        self, trainer, store, consumer, tenant_id
    ):
        await store.set_experiment(
            tenant_id,
            EXPERIMENT,
            {
                "id": EXPERIMENT,
                "policy": "BetaTSPolicy",
                "policy_params": {"alpha_prior": 2.0, "beta_prior": 2.0},
                "pool": {
                    "arms": [{"id": "arm-0", "index": 0}, {"id": "arm-1", "index": 1}]
                },
            },
        )
        messages = await deliver(consumer, [feedback(tenant_id)])

        await trainer.train_experiment(tenant_id, EXPERIMENT, messages)

        params = (await store.read_learning(tenant_id, EXPERIMENT)).params
        assert params["alpha"] == [3.0, 2.0]
        assert params["beta"] == [2.0, 2.0]

    async def test_trains_on_existing_params(
        self,
        trainer,
        store,
        consumer,
        tenant_id,
        experiment,
        sample_beta_ts_params,
    ):
        await store.set_params(
            tenant_id,
            EXPERIMENT,
            {**sample_beta_ts_params, "alpha": [5.0, 1.0, 1.0]},
        )
        messages = await deliver(consumer, [feedback(tenant_id)])

        await trainer.train_experiment(tenant_id, EXPERIMENT, messages)

        params = (await store.read_learning(tenant_id, EXPERIMENT)).params
        assert params["alpha"][0] == 6.0

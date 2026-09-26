from __future__ import annotations

import random
import time
import uuid
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import ClassVar

import gevent
from locust import User
from locust import between
from locust import events
from locust import task

from bin.loadtest.client import ProxyClient
from bin.loadtest.client import SelectResult
from bin.loadtest.config import MANUAL_POLICIES
from bin.loadtest.config import settings


@dataclass
class PendingFeedback:
    request_id: str
    arm_index: int


@dataclass
class ExperimentInfo:
    experiment_id: str
    pool_id: str
    policy: str
    arm_reward_probs: list[float]
    is_auto: bool = False
    user_count: int = 0


class BanditUser(User):
    """
    simulates users interacting with bandit experiments.

    works identically for auto (meta-bandit) and manual experiments —
    the select/feedback API is the same regardless of mode.
    users are round-robin assigned across all created experiments.
    """

    wait_time = between(0.1, 0.5)

    experiments: ClassVar[list[ExperimentInfo]] = []
    _setup_done: ClassVar[bool] = False
    _assignment_lock: ClassVar[Lock] = Lock()
    _user_counter: ClassVar[int] = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client: ProxyClient | None = None
        self.assigned_experiment: ExperimentInfo | None = None
        self.pending_feedbacks: deque[PendingFeedback] = deque(maxlen=100)

    def on_start(self) -> None:
        self.client = ProxyClient()
        self.client.connect()
        self._assign_experiment()

    def on_stop(self) -> None:
        if self.client:
            self.client.close()
        self._release_experiment()

    def _assign_experiment(self) -> None:
        with BanditUser._assignment_lock:
            if not BanditUser.experiments:
                return
            idx = BanditUser._user_counter % len(BanditUser.experiments)
            BanditUser._user_counter += 1
            exp = BanditUser.experiments[idx]
            exp.user_count += 1
            self.assigned_experiment = exp

    def _release_experiment(self) -> None:
        if self.assigned_experiment:
            with BanditUser._assignment_lock:
                self.assigned_experiment.user_count = max(
                    0, self.assigned_experiment.user_count - 1
                )

    @task(10)
    def select_arm(self) -> None:
        if not self.assigned_experiment or not self.client:
            return

        context_id = str(uuid.uuid4())
        context_vector = [random.random() for _ in range(settings.context_vector_dim)]
        context_metadata = {
            "device": random.choice(["mobile", "desktop", "tablet"]),
            "region": random.choice(["us-east", "us-west", "eu", "apac"]),
            "user_tier": random.choice(["free", "premium", "enterprise"]),
        }

        start_time = time.perf_counter()
        try:
            result: SelectResult = self.client.select(
                experiment_id=self.assigned_experiment.experiment_id,
                context_id=context_id,
                context_vector=context_vector,
                context_metadata=context_metadata,
            )
            response_time_ms = (time.perf_counter() - start_time) * 1000

            events.request.fire(
                request_type="http",
                name="Select",
                response_time=response_time_ms,
                response_length=0,
                exception=None,
                context={},
            )

            if random.random() < settings.feedback_probability:
                pending = PendingFeedback(
                    request_id=result.request_id,
                    arm_index=result.arm_index,
                )
                self.pending_feedbacks.append(pending)
                delay_ms = random.randint(
                    settings.feedback_delay_min_ms,
                    settings.feedback_delay_max_ms,
                )
                gevent.spawn_later(delay_ms / 1000.0, self._send_feedback, pending)

        except Exception as e:
            response_time_ms = (time.perf_counter() - start_time) * 1000
            events.request.fire(
                request_type="http",
                name="Select",
                response_time=response_time_ms,
                response_length=0,
                exception=e,
                context={},
            )

    @task(1)
    def health_check(self) -> None:
        if not self.client:
            return

        start_time = time.perf_counter()
        try:
            self.client.health_check()
            response_time_ms = (time.perf_counter() - start_time) * 1000
            events.request.fire(
                request_type="http",
                name="Health",
                response_time=response_time_ms,
                response_length=0,
                exception=None,
                context={},
            )
        except Exception as e:
            response_time_ms = (time.perf_counter() - start_time) * 1000
            events.request.fire(
                request_type="http",
                name="Health",
                response_time=response_time_ms,
                response_length=0,
                exception=e,
                context={},
            )

    def _send_feedback(self, pending: PendingFeedback) -> None:
        if not self.client or not self.client.is_connected:
            return

        # per-arm reward probability — gives the bandit a real signal to learn from
        prob = settings.reward_success_probability
        if self.assigned_experiment and pending.arm_index < len(
            self.assigned_experiment.arm_reward_probs
        ):
            prob = self.assigned_experiment.arm_reward_probs[pending.arm_index]
        reward = 1.0 if random.random() < prob else 0.0

        start_time = time.perf_counter()
        try:
            self.client.feedback(
                request_id=pending.request_id,
                reward=reward,
            )
            response_time_ms = (time.perf_counter() - start_time) * 1000
            events.request.fire(
                request_type="http",
                name="Feedback",
                response_time=response_time_ms,
                response_length=0,
                exception=None,
                context={},
            )
        except Exception as e:
            response_time_ms = (time.perf_counter() - start_time) * 1000
            events.request.fire(
                request_type="http",
                name="Feedback",
                response_time=response_time_ms,
                response_length=0,
                exception=e,
                context={},
            )


# --------------------------------------------------------------------------- #
# setup / teardown
# --------------------------------------------------------------------------- #


@events.test_start.add_listener
def on_test_start(environment, **kwargs):  # noqa
    if BanditUser._setup_done:  # noqa
        return

    client = ProxyClient()
    client.connect()

    try:
        for i in range(settings.num_experiments):
            suffix = uuid.uuid4().hex[:8]

            pool_id = client.create_pool(
                name=f"loadtest-pool-{i}-{suffix}",
                num_arms=settings.num_arms,
            )

            if settings.auto:
                policy = "auto"
                policy_params: dict = {
                    "reward_type": "binary",
                    "use_context": False,
                }
            else:
                policy = random.choice(MANUAL_POLICIES)
                policy_params = {}

            experiment_id = client.create_experiment(
                name=f"loadtest-exp-{i}-{suffix}",
                pool_id=pool_id,
                policy=policy,
                policy_params=policy_params,
            )

            # per-arm reward probabilities sampled from configured range
            arm_reward_probs = [
                random.uniform(settings.reward_prob_min, settings.reward_prob_max)
                for _ in range(settings.num_arms)
            ]

            BanditUser.experiments.append(
                ExperimentInfo(
                    experiment_id=experiment_id,
                    pool_id=pool_id,
                    policy=policy,
                    arm_reward_probs=arm_reward_probs,
                    is_auto=(policy == "auto"),
                )
            )

            mode = "auto" if policy == "auto" else policy
            probs_str = ", ".join(f"{p:.2f}" for p in arm_reward_probs)
            print(
                f"[{i + 1}/{settings.num_experiments}] created experiment {experiment_id} ({mode})"
            )
            print(f"  arm reward probabilities: [{probs_str}]")

        BanditUser._setup_done = True

    finally:
        client.close()


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):  # noqa
    if not BanditUser._setup_done:  # noqa
        return

    client = ProxyClient()
    client.connect()

    try:
        for exp in BanditUser.experiments:
            try:
                client.delete_experiment(exp.experiment_id)
                print(f"deleted experiment: {exp.experiment_id}")
            except Exception as e:
                print(f"failed to delete experiment {exp.experiment_id}: {e}")

            try:
                client.delete_pool(exp.pool_id)
                print(f"deleted pool: {exp.pool_id}")
            except Exception as e:
                print(f"failed to delete pool {exp.pool_id}: {e}")

    finally:
        client.close()
        BanditUser._setup_done = False
        BanditUser.experiments.clear()

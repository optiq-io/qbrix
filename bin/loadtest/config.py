from __future__ import annotations

from pydantic_settings import BaseSettings

# stochastic policies safe for load testing (no context required, binary reward)
MANUAL_POLICIES = [
    "BetaTSPolicy",
    "UCB1TunedPolicy",
    "EpsilonPolicy",
    "EXP3Policy",
    "FPLPolicy",
    "MOSSPolicy",
    "RandomPolicy",
]


class LoadTestSettings(BaseSettings):
    proxy_host: str = "localhost"
    proxy_port: int = 8080
    proxy_scheme: str = "http"
    api_key: str = ""

    # experiment setup
    num_experiments: int = 1
    num_arms: int = 5
    auto: bool = True  # use meta-bandit by default

    # behavior tuning
    feedback_probability: float = 0.7
    feedback_delay_min_ms: int = 100
    feedback_delay_max_ms: int = 2000
    reward_success_probability: float = 0.02  # fallback if arm probs not available
    reward_prob_min: float = 0.03
    reward_prob_max: float = 0.01

    # context generation
    context_vector_dim: int = 10

    model_config = {"env_prefix": "LOADTEST_"}

    @property
    def proxy_address(self) -> str:
        return f"{self.proxy_scheme}://{self.proxy_host}:{self.proxy_port}"


settings = LoadTestSettings()

"""unit tests for RolloutConfig.is_in_rollout stability."""

from __future__ import annotations

import os
import subprocess
import sys

from proxysvc.mod.gate.model.experiment import RolloutConfig


class TestDeterminism:

    def test_deterministic_for_same_identifier(self):
        config = RolloutConfig(percentage=37.0)
        results = {config.is_in_rollout("visitor-1") for _ in range(50)}
        assert len(results) == 1

    def test_known_identifier_known_bucket(self):
        # blake2b(digest_size=8) of these identifiers buckets to 11 and 44 —
        # pins the algorithm so an accidental change is caught here, not in prod
        config = RolloutConfig(percentage=12.0)
        assert config.is_in_rollout("visitor-1") is True  # bucket 11 < 12
        assert config.is_in_rollout("visitor-2") is False  # bucket 44 >= 12

    def test_stable_across_process_with_different_hash_seed(self):
        # this is the actual bug: builtin hash() is salted per-process, so a
        # single-process test could never have caught it. run in subprocesses
        # with different PYTHONHASHSEED and confirm identical output.
        script = (
            "from proxysvc.mod.gate.model.experiment import RolloutConfig; "
            "print(RolloutConfig(percentage=50.0).is_in_rollout('visitor-42'))"
        )
        outputs = set()
        for seed in ("0", "111", "222"):
            result = subprocess.run(
                [sys.executable, "-c", script],
                env={**os.environ, "PYTHONHASHSEED": seed},
                capture_output=True,
                text=True,
                check=True,
            )
            outputs.add(result.stdout.strip())
        assert len(outputs) == 1


class TestBoundaries:

    def test_zero_percent_always_excludes(self):
        config = RolloutConfig(percentage=0.0)
        for identifier in ["a", "b", "c", "visitor-1", "visitor-2"]:
            assert config.is_in_rollout(identifier) is False

    def test_hundred_percent_always_includes(self):
        config = RolloutConfig(percentage=100.0)
        for identifier in ["a", "b", "c", "visitor-1", "visitor-2"]:
            assert config.is_in_rollout(identifier) is True


class TestMonotonicRamp:

    def test_membership_never_reverts_as_percentage_increases(self):
        # the product promise ("ramping up never reshuffles the visitors
        # already in") depends on this: for a fixed identifier, membership is
        # monotonic non-decreasing as percentage climbs from 0 to 100
        identifiers = ["visitor-1", "visitor-2", "user-alpha", "user-beta", "x", "y"]
        for identifier in identifiers:
            was_in = False
            for percentage in range(0, 101):
                is_in = RolloutConfig(percentage=float(percentage)).is_in_rollout(
                    identifier
                )
                if was_in:
                    assert is_in, (
                        f"{identifier} dropped out of rollout at {percentage}% "
                        f"after being in at a lower percentage"
                    )
                was_in = is_in

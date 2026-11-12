from __future__ import annotations

import pytest

from proxysvc.core.targeting import OPERATORS
from proxysvc.core.targeting import bucket
from proxysvc.core.targeting import holds

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "operator, actual, expected, result",
    [
        ("is", "mobile", "mobile", True),
        ("is", "desktop", "mobile", False),
        ("is_not", "desktop", "mobile", True),
        ("is_not", "mobile", "mobile", False),
        ("in", "NL", ["NL", "BE"], True),
        ("in", "DE", ["NL", "BE"], False),
        ("not_in", "DE", ["NL", "BE"], True),
        ("not_in", "NL", ["NL", "BE"], False),
        ("contains", "pro-annual", "annual", True),
        ("contains", "pro-monthly", "annual", False),
        ("not_contains", "pro-monthly", "annual", True),
        ("gt", 3, 2, True),
        ("gt", 2, 2, False),
        ("gte", 2, 2, True),
        ("lt", 1, 2, True),
        ("lte", 2, 2, True),
        ("lte", 3, 2, False),
    ],
)
def test_each_operator(operator, actual, expected, result):
    assert holds(operator, actual, expected) is result


@pytest.mark.parametrize(
    "operator, actual, expected",
    [
        ("gt", "abc", 5),
        ("lt", None, 5),
        ("contains", 5, "a"),
        ("in", "NL", 5),
    ],
)
def test_a_comparison_the_values_cant_make_is_false(operator, actual, expected):
    assert holds(operator, actual, expected) is False


def test_every_operator_is_handled():
    for operator in OPERATORS:
        holds(operator, "a", ["a"])


def test_an_unknown_operator_raises():
    with pytest.raises(ValueError):
        holds("eq", "a", "a")


def test_bucket_is_stable_and_in_range():
    assert bucket("visitor-1") == bucket("visitor-1") == 11
    assert all(0 <= bucket(f"u-{n}") < 100 for n in range(500))

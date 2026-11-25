"""a loop is mentioned only explicitly: qbrix:<key> or its link on this
install's console in text, qbrix/<key> in a branch. a bare key, another host
or a key no loop could have names nothing."""

from __future__ import annotations

import pytest

from proxysvc.mod.github.mention import branch_keys
from proxysvc.mod.github.mention import mentioned_keys
from proxysvc.mod.github.mention import squashed_number

pytestmark = pytest.mark.unit

CONSOLE = "https://console.example.com"


def _keys(*texts: str | None, branch: str | None = None) -> list[str]:
    return mentioned_keys(texts, console_origin=CONSOLE, branch=branch)


@pytest.mark.parametrize(
    "text",
    [
        "qbrix:checkout-headline",
        "Try three headlines (qbrix:checkout-headline)",
        "Closes `qbrix:checkout-headline`.",
        "QBRIX:Checkout-Headline",
        "see https://console.example.com/loops/checkout-headline",
        "see https://console.example.com/next/loops/checkout-headline/history?x=1",
        "[the loop](https://CONSOLE.example.com/next/loops/checkout-headline#results)",
    ],
)
def test_an_explicit_mention_names_the_loop(text):
    assert _keys(text) == ["checkout-headline"]


@pytest.mark.parametrize(
    "text",
    [
        "checkout-headline",
        "myqbrix:checkout-headline",
        "qbrix: checkout-headline",
        "https://other.example.com/loops/checkout-headline",
        "https://console.example.com.evil.com/loops/checkout-headline",
        "https://console.example.com/metrics/checkout-headline",
        "qbrix:-headline",
        "qbrix:" + "a" * 65,
        "",
        None,
    ],
)
def test_anything_else_names_nothing(text):
    assert _keys(text) == []


def test_each_loop_once_in_order():
    assert _keys(
        "qbrix:checkout-headline and qbrix:pricing-page",
        "again qbrix:checkout-headline",
        branch="qbrix/onboarding",
    ) == ["checkout-headline", "pricing-page", "onboarding"]


def test_a_key_may_be_as_long_as_a_loop_key():
    assert _keys("qbrix:" + "a" * 64) == ["a" * 64]


@pytest.mark.parametrize(
    ("branch", "keys"),
    [
        ("qbrix/checkout-headline", ["checkout-headline"]),
        ("ada/qbrix/checkout-headline", ["checkout-headline"]),
        ("qbrix/checkout-headline/copy", ["checkout-headline"]),
        ("checkout-headline", []),
        ("feature/checkout-headline", []),
        ("qbrix", []),
        ("qbrix-checkout-headline", []),
    ],
)
def test_a_branch_names_a_loop_with_qbrix_slash_key(branch, keys):
    assert branch_keys(branch) == keys


@pytest.mark.parametrize(
    ("message", "number"),
    [
        ("Try three checkout headlines (#42)", 42),
        ("Try three checkout headlines (#42)\n\nqbrix:checkout-headline", 42),
        ("Try three checkout headlines\n\nsee (#42)", None),
        ("Merge pull request #42 from ada/qbrix/checkout-headline", None),
    ],
)
def test_a_squash_merge_names_its_pull_request_on_the_first_line(message, number):
    assert squashed_number(message) == number

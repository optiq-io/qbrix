"""loop_get's wiring is code that runs: a select for the loop's key with its
fallback offline, then an outcome, against this install, in each SDK's next
pre-release."""

from __future__ import annotations

import ast

import pytest

from proxysvc.transport.mcp.wire import JAVASCRIPT_INSTALL
from proxysvc.transport.mcp.wire import PYTHON_INSTALL
from proxysvc.transport.mcp.wire import javascript
from proxysvc.transport.mcp.wire import python

pytestmark = pytest.mark.unit

LOOP = {
    "key": "checkout-headline",
    "fallback": "control",
    "metric": {"type": "conversion"},
    "options": [
        {"key": "control", "config": {"headline": "Buy now", "bold": True}},
        {"key": "urgency", "config": {"headline": "Only 3 left"}},
    ],
}


def test_the_python_snippet_parses_and_carries_the_fallback():
    code = python(LOOP, "https://qbrix.example.com")

    ast.parse(code)
    assert code.startswith(f"# {PYTHON_INSTALL}")
    assert 'base_url="https://qbrix.example.com"' in code
    assert "{'key': 'control', 'config': {'headline': 'Buy now', 'bold': True}}" in code


def test_the_python_snippet_pins_the_pre_release_exactly():
    assert "==" in PYTHON_INSTALL
    assert "--pre" not in PYTHON_INSTALL


def test_the_javascript_snippet_carries_the_fallback_as_json():
    code = javascript(LOOP, "https://qbrix.example.com")

    assert code.startswith(f"// {JAVASCRIPT_INSTALL}")
    assert '{"key": "control", "config": {"headline": "Buy now", "bold": true}}' in code
    assert 'select(\n  "checkout-headline"' in code


def test_a_fallback_without_config_sends_an_empty_one():
    loop = {**LOOP, "options": [{"key": "control", "config": None}]}

    assert "'config': {}" in python(loop, "http://localhost:8080")

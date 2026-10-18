"""the destination a verification link may carry back to the console."""

from __future__ import annotations

import pytest

from proxysvc.mod.auth.redirect import MAX_REDIRECT_LENGTH
from proxysvc.mod.auth.redirect import safe_redirect


@pytest.mark.parametrize(
    "value",
    [
        "/experiments",
        "/experiments/abc?tab=arms",
        "/pools#arms",
        "/a//b",
    ],
)
def test_console_paths_are_kept(value):
    assert safe_redirect(value) == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "/",
        "https://example.com",
        "//example.com",
        "/\\example.com",
        "\\\\example.com",
        "javascript:alert(1)",
        "experiments",
        "/experiments\n",
        "/\texample.com",
        "/" + "x" * MAX_REDIRECT_LENGTH,
    ],
)
def test_anything_else_is_dropped(value):
    assert safe_redirect(value) is None

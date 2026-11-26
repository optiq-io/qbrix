from __future__ import annotations

import pytest

from proxysvc.mod.docs.slug import Slugger
from proxysvc.mod.docs.slug import heading_text
from proxysvc.mod.docs.slug import slug

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "heading, anchor",
    [
        ("Checkout & CTA conversion", "checkout--cta-conversion"),
        ("API (`PROXY_`)", "api-proxy_"),
        ("`is_fallback` vs `is_default`", "is_fallback-vs-is_default"),
        (
            "`feedback()` is a no-op without a token",
            "feedback-is-a-no-op-without-a-token",
        ),
        ("Events from anywhere: `track`", "events-from-anywhere-track"),
        ("What a [loop](/docs/loops) *learns* from", "what-a-loop-learns-from"),
        ("Read a loop's cycles", "read-a-loops-cycles"),
        ("Café ½ — done", "café---done"),
    ],
)
def test_anchors_match_the_docs_site(heading, anchor):
    assert slug(heading_text(heading)) == anchor


def test_repeated_headings_count_up_like_github_slugger():
    slugger = Slugger()

    assert [slugger.slug(t) for t in ("Errors", "Errors", "Errors-1", "Errors")] == [
        "errors",
        "errors-1",
        "errors-1-1",
        "errors-2",
    ]

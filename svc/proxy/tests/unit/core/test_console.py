"""every console link the proxy builds lands on a route listed in
console_routes.json, which the console's own test holds to its pages."""

from __future__ import annotations

import json
import re
from importlib import resources
from urllib.parse import urlsplit

import pytest

from proxysvc.core import console

ORIGIN = "https://console.acme.test"

ROUTES = json.loads(
    resources.files("proxysvc.core").joinpath("console_routes.json").read_text()
)


def _pattern(route: str) -> re.Pattern[str]:
    return re.compile(
        "".join(
            "/[^/]+" if part.startswith("[") else "/" + re.escape(part)
            for part in route.strip("/").split("/")
        )
        + "$"
    )


LINKED = [_pattern(route) for route in ROUTES["routes"] + ROUTES["pending"]]

LINKS = {
    "loop": console.loop_url(ORIGIN, "checkout/headline"),
    "history": console.history_url(ORIGIN, "checkout-headline"),
    "loop change": console.change_url(ORIGIN, "loop", "checkout-headline", "c1"),
    "metric change": console.change_url(ORIGIN, "metric", "purchase", "c1"),
    "changes": console.changes_url(ORIGIN, "c1"),
}


def test_routes_sit_under_the_console_base():
    for route in ROUTES["routes"] + ROUTES["pending"]:
        assert route.startswith(f"{console.BASE}/"), route


@pytest.mark.parametrize("name", LINKS)
def test_link_lands_on_a_listed_route(name):
    url = urlsplit(LINKS[name])
    assert f"{url.scheme}://{url.netloc}" == ORIGIN
    assert any(pattern.match(url.path) for pattern in LINKED), url.path


def test_a_key_with_a_slash_stays_one_segment():
    assert console.loop_url(ORIGIN, "a/b").endswith(f"{console.BASE}/loops/a%2Fb")

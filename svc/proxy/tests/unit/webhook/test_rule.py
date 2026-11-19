"""a self-hosted webhook may post to any http(s) address; the cloud only over
https to an address on the public internet, checked against every address
its host resolves to."""

from __future__ import annotations

import pytest

from proxysvc.core.error import WebhookURLError
from proxysvc.mod.webhook.rule import masked
from proxysvc.mod.webhook.rule import route

pytestmark = pytest.mark.unit

PUBLIC = "93.184.216.34"


def _resolving_to(*addresses: str):
    async def resolve(host: str) -> list[str]:
        return list(addresses)

    return resolve


async def _unresolvable(host: str) -> list[str]:
    raise OSError("no such host")


@pytest.mark.parametrize(
    "url",
    [
        "http://alerts.internal/hook",
        "https://10.0.0.5/",
        "http://localhost:9000/x",
        "https://hooks.slack.com/services/T/B/x",
    ],
)
async def test_self_hosted_accepts_any_http_address(url):
    where = await route(url, public_only=False, resolver=_unresolvable)

    assert where.target == url
    assert where.host is None


@pytest.mark.parametrize(
    "url, resolves, message",
    [
        ("http://hooks.example/x", (PUBLIC,), "https"),
        ("https://10.0.0.5/", ("10.0.0.5",), "isn't on the public internet"),
        ("https://inward.example/x", ("192.168.1.4",), "public internet"),
        ("https://mixed.example/x", (PUBLIC, "127.0.0.1"), "public internet"),
        ("https://[::ffff:10.0.0.1]/", ("::ffff:10.0.0.1",), "public internet"),
    ],
)
async def test_cloud_refuses_what_isnt_public_https(url, resolves, message):
    with pytest.raises(WebhookURLError, match=message):
        await route(url, public_only=True, resolver=_resolving_to(*resolves))


async def test_cloud_refuses_a_host_that_doesnt_resolve():
    with pytest.raises(WebhookURLError, match="doesn't resolve"):
        await route(
            "https://nowhere.example/x", public_only=True, resolver=_unresolvable
        )


async def test_cloud_pins_the_vetted_address():
    where = await route(
        "https://hooks.example:8443/p?q=1",
        public_only=True,
        resolver=_resolving_to(PUBLIC),
    )

    assert where.target == f"https://{PUBLIC}:8443/p?q=1"
    assert where.host == "hooks.example"


@pytest.mark.parametrize("public_only", [True, False])
@pytest.mark.parametrize(
    "url, message",
    [
        ("ftp://hooks.example/x", "address"),
        ("https://", "address"),
        ("https://user:pw@hooks.example/x", "user name or password"),
        ("https://hooks.example:99999/x", "isn't a valid url"),
        ("https://hooks.example/" + "a" * 2048, "2048"),
    ],
)
async def test_both_editions_refuse_a_malformed_address(public_only, url, message):
    with pytest.raises(WebhookURLError, match=message):
        await route(url, public_only=public_only, resolver=_resolving_to(PUBLIC))


@pytest.mark.parametrize(
    "url, shown",
    [
        ("https://hooks.slack.com/services/T0/B0/secret", "https://hooks.slack.com/…"),
        ("http://alerts.internal:9000/", "http://alerts.internal:9000"),
        ("https://hooks.example?token=x", "https://hooks.example/…"),
    ],
)
def test_masked_stops_at_the_host(url, shown):
    assert masked(url) == shown


async def test_an_address_literal_is_judged_as_written_not_resolved():
    with pytest.raises(WebhookURLError, match="public internet"):
        await route(
            "https://10.0.0.5/", public_only=True, resolver=_resolving_to(PUBLIC)
        )

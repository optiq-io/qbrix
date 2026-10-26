"""a client metadata document is fetched only from the public internet: over
https on the default port, from an address checked before connecting, without
redirects, within 5 seconds and 64 KB."""

from __future__ import annotations

import httpx
import pytest

from proxysvc.core.error import OAuthError
from proxysvc.mod.oauth import cimd
from proxysvc.mod.oauth.cimd import CIMDFetcher

pytestmark = pytest.mark.unit

URL = "https://client.example/meta.json"
DOCUMENT = {
    "client_id": URL,
    "client_name": "Doc Client",
    "redirect_uris": ["https://client.example/cb"],
}


class _Server:
    """a mock transport that records whether anything connected."""

    def __init__(self, respond):
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._respond(request)

        return httpx.MockTransport(handle)


def _resolving_to(*addresses: str):
    async def resolve(host: str) -> list[str]:
        return list(addresses)

    return resolve


def _fetcher(server: _Server, *addresses: str) -> CIMDFetcher:
    return CIMDFetcher(
        resolver=_resolving_to(*(addresses or ("93.184.216.34",))),
        transport=server.transport(),
    )


def _serving(document=DOCUMENT, status=200, headers=None):
    return _Server(lambda r: httpx.Response(status, json=document, headers=headers))


async def test_fetches_from_the_vetted_address_with_the_host_name():
    server = _serving()

    client = await _fetcher(server).client(URL)

    assert client.client_id == URL
    assert client.name == "Doc Client"
    [request] = server.requests
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "client.example"
    assert request.extensions["sni_hostname"] == "client.example"


async def test_a_document_is_cached():
    server = _serving()
    fetcher = _fetcher(server)

    await fetcher.client(URL)
    await fetcher.client(URL)

    assert len(server.requests) == 1


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "::1",
        "fe80::1",
        "fd00::1",
        "::ffff:127.0.0.1",
        "0.0.0.0",
    ],
)
async def test_a_private_address_is_refused_without_connecting(address):
    server = _serving()

    with pytest.raises(OAuthError) as refused:
        await _fetcher(server, address).client(URL)

    assert refused.value.error == "invalid_client"
    assert server.requests == []


async def test_one_private_answer_among_public_ones_is_refused():
    server = _serving()

    with pytest.raises(OAuthError):
        await _fetcher(server, "93.184.216.34", "10.0.0.5").client(URL)

    assert server.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "http://client.example/meta.json",
        "https://client.example:8443/meta.json",
        "https://user:pw@client.example/meta.json",
    ],
)
async def test_only_https_on_the_default_port(url):
    server = _serving()

    with pytest.raises(OAuthError):
        await _fetcher(server).client(url)

    assert server.requests == []


async def test_a_redirect_is_refused():
    server = _serving(status=302, headers={"location": "http://10.0.0.5/"})

    with pytest.raises(OAuthError) as refused:
        await _fetcher(server).client(URL)

    assert "302" in refused.value.description
    assert len(server.requests) == 1


async def test_a_document_over_64_kb_is_refused():
    server = _Server(lambda r: httpx.Response(200, content=b"x" * (64 * 1024 + 1)))

    with pytest.raises(OAuthError) as refused:
        await _fetcher(server).client(URL)

    assert "64 KB" in refused.value.description


async def test_a_slow_document_is_refused():
    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(OAuthError) as refused:
        await _fetcher(_Server(slow)).client(URL)

    assert "too long" in refused.value.description


def test_the_timeout_is_5_seconds():
    assert cimd.TIMEOUT_SEC == 5.0


async def test_an_unresolvable_host_is_refused():
    async def fail(host):
        raise OSError("no such host")

    with pytest.raises(OAuthError):
        await CIMDFetcher(resolver=fail).client(URL)


async def test_a_document_for_another_client_is_refused():
    server = _serving({**DOCUMENT, "client_id": "https://other.example/meta.json"})

    with pytest.raises(OAuthError):
        await _fetcher(server).client(URL)

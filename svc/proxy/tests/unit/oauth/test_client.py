"""a redirect uri matches exactly, except a loopback one may name any port; a
self-registered client may redirect only to https, loopback http, or, for a
native app, its own scheme."""

from __future__ import annotations

import pytest

from proxysvc.core.error import OAuthError
from proxysvc.mod.oauth.client import check_redirect_uris
from proxysvc.mod.oauth.client import documented_client
from proxysvc.mod.oauth.client import redirect_matches
from proxysvc.mod.oauth.client import registered_client

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "registered, given, matches",
    [
        (("https://app.example/cb",), "https://app.example/cb", True),
        (("https://app.example/cb",), "https://app.example/cb/", False),
        (("https://app.example/cb",), "https://app.example:8443/cb", False),
        (("http://127.0.0.1/cb",), "http://127.0.0.1:53111/cb", True),
        (("http://localhost:3000/cb",), "http://localhost:4000/cb", True),
        (("http://[::1]/cb",), "http://[::1]:9000/cb", True),
        (("http://127.0.0.1/cb",), "http://127.0.0.1:53111/other", False),
        (("http://127.0.0.1/cb",), "http://localhost:53111/cb", False),
        (("http://127.0.0.1/cb",), "http://127.0.0.2:53111/cb", False),
    ],
)
def test_redirect_matching(registered, given, matches):
    assert redirect_matches(registered, given) is matches


@pytest.mark.parametrize(
    "uris, native",
    [
        (["https://app.example/cb"], False),
        (["http://127.0.0.1/cb", "http://localhost:8080/cb"], False),
        (["cursor://anysphere/oauth"], True),
    ],
)
def test_accepted_redirect_uris(uris, native):
    assert check_redirect_uris(uris, native=native) == tuple(uris)


@pytest.mark.parametrize(
    "uris, native",
    [
        (["http://app.example/cb"], False),
        (["https://app.example/cb#x"], False),
        (["cursor://anysphere/oauth"], False),
        (["javascript://alert(1)"], True),
        ([], False),
        ("https://app.example/cb", False),
        (["https://app.example/cb"] * 11, False),
    ],
)
def test_refused_redirect_uris(uris, native):
    with pytest.raises(OAuthError) as refused:
        check_redirect_uris(uris, native=native)
    assert refused.value.error == "invalid_redirect_uri"


def test_registrations_of_one_client_share_an_identity():
    meta = {"client_name": "Claude Code", "redirect_uris": ["http://127.0.0.1/cb"]}

    first = registered_client("id-1", meta)
    second = registered_client("id-2", meta)

    assert first.identity == second.identity == "Claude Code"
    assert registered_client("id-3", {**meta, "software_id": "cc"}).identity == "cc"


def test_a_nameless_registration_is_its_own_client():
    client = registered_client("id-1", {"redirect_uris": ["http://127.0.0.1/cb"]})

    assert client.identity == "id-1"
    assert client.name == "an unnamed client"


def test_a_document_must_name_its_own_url():
    with pytest.raises(OAuthError) as refused:
        documented_client(
            "https://a.example/meta",
            {
                "client_id": "https://b.example/meta",
                "redirect_uris": ["https://a.example/cb"],
            },
        )
    assert refused.value.error == "invalid_client"

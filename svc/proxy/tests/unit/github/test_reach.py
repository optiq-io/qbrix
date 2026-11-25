"""github can only send events to a public https address, so an install whose
public address is plain http, a private host or a private ip says so before
anyone starts connecting."""

from __future__ import annotations

import pytest

from proxysvc.mod.github.reach import unreachable_reason

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "origin",
    [
        "https://qbrix.example.com",
        "https://abc-def.trycloudflare.com",
        "https://93.184.216.34",
        "https://qbrix.example.com:8443",
    ],
)
def test_a_public_https_address_is_not_ruled_out(origin):
    assert unreachable_reason(origin) is None


@pytest.mark.parametrize(
    "origin",
    [
        "http://qbrix.example.com",
        "http://localhost:8080",
    ],
)
def test_plain_http_is_ruled_out(origin):
    assert "isn't an https address" in unreachable_reason(origin)


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost:8080",
        "https://qbrix.localhost",
        "https://qbrix.internal:8000",
        "https://box.local",
        "https://nas.lan",
        "https://router.home.arpa",
        "https://qbrix",
        "https://127.0.0.1",
        "https://10.0.0.4",
        "https://192.168.1.4",
        "https://172.16.0.1",
        "https://169.254.1.1",
        "https://[::1]",
        "https://[fd00::1]",
    ],
)
def test_a_private_host_is_ruled_out(origin):
    assert "private address" in unreachable_reason(origin)


def test_the_note_names_the_address():
    note = unreachable_reason("https://qbrix.internal:8000")

    assert note.startswith("GitHub can't reach qbrix.internal:8000")
    assert "PROXY_PUBLIC_URL" in note

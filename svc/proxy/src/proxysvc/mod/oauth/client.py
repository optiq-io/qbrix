from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from proxysvc.core.error import InvalidIdentityError
from proxysvc.core.error import OAuthError
from proxysvc.mod.auth.identity import clean_name

MAX_REDIRECT_URIS = 10
MAX_URI_LENGTH = 512

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_FORBIDDEN_SCHEMES = {"javascript", "data", "file", "vbscript"}


@dataclass(frozen=True, slots=True)
class ClientIdentity:
    """a client as the authorization server knows it. identity is what makes
    two sign-ins the same client; metadata_url is set for a client identified
    by a metadata document."""

    client_id: str
    identity: str
    name: str
    uri: str | None
    redirect_uris: tuple[str, ...]
    metadata_url: str | None = None


def _is_loopback(uri: str) -> bool:
    parts = urlsplit(uri)
    return parts.scheme == "http" and parts.hostname in _LOOPBACK_HOSTS


def redirect_matches(registered: tuple[str, ...], given: str) -> bool:
    """exact match, except that a loopback redirect may name any port: a native
    client listens on whichever port is free when it signs in."""
    if given in registered:
        return True
    if not _is_loopback(given):
        return False
    wanted = urlsplit(given)
    for uri in registered:
        candidate = urlsplit(uri)
        if (
            _is_loopback(uri)
            and candidate.hostname == wanted.hostname
            and candidate.path == wanted.path
            and candidate.query == wanted.query
        ):
            return True
    return False


def _bad_metadata(description: str) -> OAuthError:
    return OAuthError("invalid_client_metadata", description)


def check_redirect_uris(value: object, *, native: bool) -> tuple[str, ...]:
    """https, or http on loopback; a native app may also use its own scheme."""
    if (
        not isinstance(value, list)
        or not value
        or len(value) > MAX_REDIRECT_URIS
        or not all(isinstance(uri, str) for uri in value)
    ):
        raise OAuthError(
            "invalid_redirect_uri",
            f"redirect_uris must list 1 to {MAX_REDIRECT_URIS} uris",
        )
    for uri in value:
        parts = urlsplit(uri)
        allowed = (
            (parts.scheme == "https" and parts.hostname)
            or _is_loopback(uri)
            or (native and parts.scheme and parts.scheme not in _FORBIDDEN_SCHEMES)
        )
        if len(uri) > MAX_URI_LENGTH or parts.fragment or not allowed:
            raise OAuthError(
                "invalid_redirect_uri",
                f"{uri!r} isn't a redirect uri this server accepts: use https, "
                "or http on localhost",
            )
    return tuple(value)


def _optional_str(metadata: dict, field: str) -> str | None:
    value = metadata.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_URI_LENGTH:
        raise _bad_metadata(f"{field} must be a string")
    return value


def client_name(metadata: dict) -> str | None:
    try:
        name = clean_name(_optional_str(metadata, "client_name"), "client_name")
    except InvalidIdentityError as e:
        raise _bad_metadata(str(e)) from e
    return name or None


def client_uri(metadata: dict) -> str | None:
    uri = _optional_str(metadata, "client_uri")
    if uri is not None and urlsplit(uri).scheme not in ("https", "http"):
        raise _bad_metadata("client_uri must be an http or https url")
    return uri


def _display_name(name: str | None, uri: str | None, fallback: str) -> str:
    if name:
        return name
    if uri:
        return urlsplit(uri).hostname or fallback
    return fallback


def registered_client(client_id: str, metadata: dict) -> ClientIdentity:
    """a client that registered itself. every registration mints a new
    client_id, so the same client is recognised by its software_id or name."""
    name = metadata.get("client_name")
    uri = metadata.get("client_uri")
    return ClientIdentity(
        client_id=client_id,
        identity=metadata.get("software_id") or name or client_id,
        name=_display_name(name, uri, "an unnamed client"),
        uri=uri,
        redirect_uris=tuple(metadata["redirect_uris"]),
    )


def documented_client(url: str, document: dict) -> ClientIdentity:
    """a client identified by the url of its metadata document."""
    if document.get("client_id") != url:
        raise OAuthError(
            "invalid_client", "the client's metadata document names another client_id"
        )
    native = document.get("application_type") == "native"
    redirect_uris = check_redirect_uris(document.get("redirect_uris"), native=native)
    try:
        name = client_name(document)
        uri = client_uri(document)
    except OAuthError as e:
        raise OAuthError("invalid_client", e.description) from e
    return ClientIdentity(
        client_id=url,
        identity=url,
        name=_display_name(name, uri, urlsplit(url).hostname or url),
        uri=uri,
        redirect_uris=redirect_uris,
        metadata_url=url,
    )

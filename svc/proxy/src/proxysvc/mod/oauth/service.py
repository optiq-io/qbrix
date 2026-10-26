from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from collections.abc import Mapping
from dataclasses import asdict
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from qbrixstore.postgres.models import OAuthClient
from qbrixstore.postgres.session import get_session
from qbrixstore.redis.client import RedisClient

from proxysvc.config import ProxySettings
from proxysvc.core.error import OAuthError
from proxysvc.core.error import OAuthRedirectError
from proxysvc.core.error import OAuthRequestNotFoundError
from proxysvc.mod.connection.service import ConnectionService
from proxysvc.mod.oauth.cimd import CIMDFetcher
from proxysvc.mod.oauth.cimd import is_document_url
from proxysvc.mod.oauth.client import ClientIdentity
from proxysvc.mod.oauth.client import check_redirect_uris
from proxysvc.mod.oauth.client import client_name
from proxysvc.mod.oauth.client import client_uri
from proxysvc.mod.oauth.client import redirect_matches
from proxysvc.mod.oauth.client import registered_client
from proxysvc.mod.oauth.metadata import SCOPE
from proxysvc.mod.oauth.metadata import authorization_server_metadata

logger = logging.getLogger(__name__)

REQUEST_TTL_SEC = 600
CODE_TTL_SEC = 60
MAX_CLIENT_ID_LENGTH = 512

_PKCE = re.compile(r"[A-Za-z0-9._~-]{43,128}")
_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")
_GRANT_TYPES = {"authorization_code", "refresh_token"}


def _request_key(request_id: str) -> str:
    return f"qbrix:oauth:request:{request_id}"


def _code_key(code: str) -> str:
    return f"qbrix:oauth:code:{hashlib.sha256(code.encode()).hexdigest()}"


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def with_query(uri: str, params: dict[str, str]) -> str:
    """the redirect uri with params added to whatever query it already has."""
    parts = urlsplit(uri)
    query = urlencode(params)
    if parts.query:
        query = f"{parts.query}&{query}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


class OAuthService:
    """qbrix as its own oauth 2.1 authorization server, for connections.

    a client is identified by a metadata document url or registers itself.
    the person approves in the console, which this server can't see: the
    authorization request waits in redis under an id the console page reads,
    and its decision returns the redirect back to the client. pending requests
    and codes live only in redis, so any replica can serve any step.
    """

    def __init__(
        self,
        *,
        redis: RedisClient,
        settings: ProxySettings,
        connections: ConnectionService,
        fetcher: CIMDFetcher,
    ):
        self._redis = redis
        self._settings = settings
        self._connections = connections
        self._fetcher = fetcher

    @property
    def issuer(self) -> str:
        return self._settings.public_origin

    def metadata(self) -> dict:
        return authorization_server_metadata(self._settings)

    async def register(self, metadata: Mapping) -> dict:
        """dynamic client registration (rfc 7591), public clients only."""
        if metadata.get("token_endpoint_auth_method", "none") != "none":
            raise OAuthError(
                "invalid_client_metadata",
                "only public clients register here: "
                "use token_endpoint_auth_method none",
            )
        grant_types = metadata.get("grant_types", sorted(_GRANT_TYPES))
        if not isinstance(grant_types, list) or not set(grant_types) <= _GRANT_TYPES:
            raise OAuthError(
                "invalid_client_metadata",
                "grant_types may only be authorization_code and refresh_token",
            )
        if metadata.get("response_types", ["code"]) != ["code"]:
            raise OAuthError("invalid_client_metadata", "response_types must be code")
        application_type = metadata.get("application_type", "web")
        if application_type not in ("web", "native"):
            raise OAuthError(
                "invalid_client_metadata", "application_type must be web or native"
            )
        software_id = metadata.get("software_id")
        if software_id is not None and (
            not isinstance(software_id, str) or len(software_id) > 255
        ):
            raise OAuthError("invalid_client_metadata", "software_id must be a string")
        stored = {
            "redirect_uris": list(
                check_redirect_uris(
                    metadata.get("redirect_uris"),
                    native=application_type == "native",
                )
            ),
            "client_name": client_name(metadata),
            "client_uri": client_uri(metadata),
            "software_id": software_id,
            "application_type": application_type,
            "grant_types": grant_types,
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
        async with get_session() as session:
            client = OAuthClient(client_metadata=stored)
            session.add(client)
            await session.flush()
            client_id = client.client_id
        logger.info(f"oauth client {client_id} registered")
        return {
            "client_id": client_id,
            "client_id_issued_at": int(time.time()),
            **{k: v for k, v in stored.items() if v is not None},
        }

    async def _client(self, client_id: str) -> ClientIdentity:
        if len(client_id) > MAX_CLIENT_ID_LENGTH:
            raise OAuthError("invalid_client", "client_id is too long")
        if is_document_url(client_id):
            return await self._fetcher.client(client_id)
        async with get_session() as session:
            client = await session.get(OAuthClient, client_id)
            if client is None:
                raise OAuthError(
                    "invalid_client", "unknown client_id: register the client first"
                )
            return registered_client(client.client_id, client.client_metadata)

    async def authorize(self, params: Mapping[str, str]) -> str:
        """check an authorization request and park it for the person to decide.
        returns where to send the browser: the console's approval page."""
        client_id = params.get("client_id")
        if not client_id:
            raise OAuthError("invalid_request", "client_id is required")
        client = await self._client(client_id)
        redirect_uri = params.get("redirect_uri")
        if not redirect_uri or not redirect_matches(client.redirect_uris, redirect_uri):
            raise OAuthError(
                "invalid_request",
                "redirect_uri must be one of the client's registered redirect uris",
            )
        state = params.get("state", "")

        def refuse(error: str, description: str) -> OAuthRedirectError:
            return OAuthRedirectError(error, description, redirect_uri, state)

        if params.get("response_type") != "code":
            raise refuse("unsupported_response_type", "response_type must be code")
        challenge = params.get("code_challenge")
        if not challenge:
            raise refuse(
                "invalid_request",
                "PKCE is required: send code_challenge with code_challenge_method S256",
            )
        if params.get("code_challenge_method") != "S256":
            raise refuse("invalid_request", "code_challenge_method must be S256")
        if not _CHALLENGE.fullmatch(challenge):
            raise refuse("invalid_request", "code_challenge isn't an S256 challenge")
        if params.get("resource") != self._settings.mcp_resource:
            raise refuse(
                "invalid_target",
                f"resource must be this server's MCP endpoint, "
                f"{self._settings.mcp_resource}",
            )
        scopes = set(params.get("scope", SCOPE).split())
        if not scopes <= {SCOPE}:
            raise refuse("invalid_scope", f"the only scope is {SCOPE}")

        request_id = secrets.token_urlsafe(24)
        pending = {
            "client": asdict(client),
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "resource": self._settings.mcp_resource,
        }
        await self._redis.client.set(
            _request_key(request_id), json.dumps(pending), ex=REQUEST_TTL_SEC
        )
        return f"{self._settings.console_origin}/authorize?request={request_id}"

    def error_redirect(self, error: OAuthRedirectError) -> str:
        return with_query(
            error.redirect_uri,
            {
                "error": error.error,
                "error_description": error.description,
                "state": error.state,
                "iss": self.issuer,
            },
        )

    async def _pending(self, request_id: str) -> dict:
        raw = await self._redis.client.get(_request_key(request_id))
        if raw is None:
            raise OAuthRequestNotFoundError(
                "this sign-in request expired or was already answered; "
                "start again from your client"
            )
        return json.loads(raw)

    async def get_request(self, request_id: str, *, name: str, email: str) -> dict:
        """what the person approving sees."""
        pending = await self._pending(request_id)
        client = pending["client"]
        return {
            "id": request_id,
            "client": {
                "name": client["name"],
                "uri": client["uri"],
                "metadata_url": client["metadata_url"],
                "registered_by_itself": client["metadata_url"] is None,
            },
            "acts_for": {"name": name, "email": email},
            "applies_at_once": True,
        }

    async def decide(
        self, request_id: str, *, user_id: str, tenant_id: str, approve: bool
    ) -> str:
        """approve or deny a request; returns the redirect back to the client."""
        raw = await self._redis.client.getdel(_request_key(request_id))
        if raw is None:
            raise OAuthRequestNotFoundError(
                "this sign-in request expired or was already answered; "
                "start again from your client"
            )
        pending = json.loads(raw)
        params = {"state": pending["state"], "iss": self.issuer}
        if not approve:
            logger.info(f"oauth request denied by user {user_id}")
            return with_query(
                pending["redirect_uri"],
                {
                    "error": "access_denied",
                    "error_description": "the person declined the connection",
                    **params,
                },
            )
        code = secrets.token_urlsafe(32)
        grant = {**pending, "user_id": user_id, "tenant_id": tenant_id}
        await self._redis.client.set(
            _code_key(code), json.dumps(grant), ex=CODE_TTL_SEC
        )
        return with_query(pending["redirect_uri"], {"code": code, **params})

    async def token(self, form: Mapping[str, str]) -> dict:
        grant_type = form.get("grant_type")
        client_id = form.get("client_id")
        if not client_id:
            raise OAuthError("invalid_request", "client_id is required")
        if grant_type == "authorization_code":
            return await self._exchange_code(form, client_id)
        if grant_type == "refresh_token":
            refresh_token = form.get("refresh_token")
            if not refresh_token:
                raise OAuthError("invalid_request", "refresh_token is required")
            tokens = await self._connections.refresh(
                refresh_token, client_id=client_id, resource=form.get("resource")
            )
            return tokens.to_dict()
        raise OAuthError(
            "unsupported_grant_type",
            "grant_type must be authorization_code or refresh_token",
        )

    async def _exchange_code(self, form: Mapping[str, str], client_id: str) -> dict:
        code = form.get("code")
        verifier = form.get("code_verifier")
        if not code or not verifier:
            raise OAuthError("invalid_request", "code and code_verifier are required")
        raw = await self._redis.client.getdel(_code_key(code))
        if raw is None:
            raise OAuthError(
                "invalid_grant", "the code is unknown, already used or expired"
            )
        grant = json.loads(raw)
        client = grant["client"]
        if client["client_id"] != client_id:
            raise OAuthError("invalid_grant", "the code was issued to another client")
        if form.get("redirect_uri") != grant["redirect_uri"]:
            raise OAuthError(
                "invalid_grant", "redirect_uri doesn't match the authorization request"
            )
        if not _PKCE.fullmatch(verifier) or not hmac.compare_digest(
            _s256(verifier), grant["code_challenge"]
        ):
            raise OAuthError(
                "invalid_grant", "code_verifier doesn't match the challenge"
            )
        resource = form.get("resource")
        if resource is not None and resource != grant["resource"]:
            raise OAuthError(
                "invalid_target", "resource doesn't match the authorization request"
            )
        tokens = await self._connections.open(
            user_id=grant["user_id"],
            tenant_id=grant["tenant_id"],
            client_identity=client["identity"],
            client_id=client_id,
            client_name=client["name"],
            client_uri=client["uri"],
            resource=grant["resource"],
        )
        return tokens.to_dict()

    async def revoke(self, token: str) -> None:
        await self._connections.revoke_token(token)

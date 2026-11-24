from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import version

import httpx
from jose import jwt

from proxysvc.core.error import GitHubUnavailableError

API = "https://api.github.com"
API_VERSION = "2022-11-28"
TIMEOUT_SEC = 10.0
PAGE_SIZE = 100
# github refuses an app jwt that lives longer than ten minutes, and allows
# for clock drift by backdating its start
JWT_BACKDATE_SEC = 60
JWT_TTL_SEC = 9 * 60


def app_jwt(app_id: int, private_key: str, *, now: float) -> str:
    """the token an app signs to act as itself, not as an installation."""
    issued = int(now) - JWT_BACKDATE_SEC
    return jwt.encode(
        {"iat": issued, "exp": issued + JWT_TTL_SEC, "iss": str(app_id)},
        private_key,
        algorithm="RS256",
    )


@dataclass(frozen=True, slots=True)
class Conversion:
    """what github hands back once a manifest becomes an app."""

    app_id: int
    slug: str
    client_id: str
    owner: str
    owner_type: str
    private_key: str
    webhook_secret: str


@dataclass(frozen=True, slots=True)
class InstallationToken:
    token: str
    expires_at: datetime


class GitHubClient:
    """the calls qbrix makes to github's api. every failure to get an answer
    raises GitHubUnavailableError; a 404 where one is expected is a result."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = API,
    ):
        self._transport = transport
        self._base_url = base_url

    async def convert_manifest(self, code: str) -> Conversion:
        response = await self._call("POST", f"/app-manifests/{code}/conversions")
        if response.status_code != 201:
            raise _unexpected(response)
        body = response.json()
        return Conversion(
            app_id=body["id"],
            slug=body["slug"],
            client_id=body["client_id"],
            owner=body["owner"]["login"],
            owner_type=body["owner"]["type"],
            private_key=body["pem"],
            webhook_secret=body["webhook_secret"],
        )

    async def installation(self, app_token: str, installation_id: int) -> dict | None:
        """the installation, or None when it isn't one of this app's."""
        response = await self._call(
            "GET", f"/app/installations/{installation_id}", token=app_token
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise _unexpected(response)
        return response.json()

    async def installation_token(
        self, app_token: str, installation_id: int
    ) -> InstallationToken:
        response = await self._call(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=app_token,
        )
        if response.status_code != 201:
            raise _unexpected(response)
        body = response.json()
        return InstallationToken(
            token=body["token"],
            expires_at=datetime.fromisoformat(body["expires_at"]),
        )

    async def repositories(self, installation_token: str) -> list[str]:
        """the full names of every repository the installation may see."""
        names: list[str] = []
        page = 1
        while True:
            response = await self._call(
                "GET",
                "/installation/repositories",
                token=installation_token,
                params={"per_page": PAGE_SIZE, "page": page},
            )
            if response.status_code != 200:
                raise _unexpected(response)
            body = response.json()
            names.extend(r["full_name"] for r in body["repositories"])
            if len(body["repositories"]) < PAGE_SIZE or len(names) >= body.get(
                "total_count", 0
            ):
                return names
            page += 1

    async def delete_installation(self, app_token: str, installation_id: int) -> None:
        """remove the installation. one already gone, or an app github no
        longer knows, counts as removed."""
        response = await self._call(
            "DELETE", f"/app/installations/{installation_id}", token=app_token
        )
        if response.status_code not in (204, 401, 404):
            raise _unexpected(response)

    async def _call(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        headers = {
            "accept": "application/vnd.github+json",
            "x-github-api-version": API_VERSION,
            "user-agent": f"qbrix/{version('proxysvc')}",
        }
        if token:
            headers["authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                transport=self._transport,
                timeout=TIMEOUT_SEC,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                return await client.request(
                    method, path, headers=headers, params=params
                )
        except httpx.HTTPError as e:
            raise GitHubUnavailableError(f"github didn't answer: {e}") from e


def _unexpected(response: httpx.Response) -> GitHubUnavailableError:
    return GitHubUnavailableError(
        f"github answered {response.status_code} to {response.request.method} "
        f"{response.request.url.path}"
    )

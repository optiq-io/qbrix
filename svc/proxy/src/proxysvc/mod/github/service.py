from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
from collections.abc import Callable
from collections.abc import Mapping
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from urllib.parse import urlencode
from uuid import uuid4

from cachebox import TTLCache
from cachebox import VTTLCache

from qbrixstore.postgres.models import GitHubApp
from qbrixstore.postgres.session import get_session

from proxysvc.config import ProxySettings
from proxysvc.core.actor import Actor
from proxysvc.core.error import GitHubAlreadyConnectedError
from proxysvc.core.error import GitHubNotConnectedError
from proxysvc.core.error import GitHubSignatureError
from proxysvc.core.error import GitHubStateError
from proxysvc.core.error import GitHubUnavailableError
from proxysvc.core.secretbox import SecretBox
from proxysvc.core.secretbox import SecretUnreadableError
from proxysvc.mod.github.client import Conversion
from proxysvc.mod.github.client import GitHubClient
from proxysvc.mod.github.client import app_jwt
from proxysvc.mod.github.reach import host_of
from proxysvc.mod.github.reach import unreachable_reason
from proxysvc.mod.github.repository import GitHubAppRepository
from proxysvc.mod.github.repository import by_events_token
from proxysvc.mod.github.state import State
from proxysvc.mod.github.state import StateSigner
from proxysvc.mod.people import People

logger = logging.getLogger(__name__)

BOX_LABEL = "github-app"
STATE_LABEL = "github-state"
PRIVATE_KEY = "github-private-key"
WEBHOOK_SECRET = "github-webhook-secret"

GITHUB = "https://github.com"
APP_NAME_MAX = 34
ORGANISATION = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")

PERMISSIONS = {"pull_requests": "read", "contents": "read", "metadata": "read"}
EVENTS = ["pull_request", "push"]

REACH_WINDOW = timedelta(seconds=60)
REPOSITORIES_TTL_SEC = 60.0
TOKEN_MARGIN = timedelta(minutes=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    """sqlite hands timestamps back naive; postgres keeps the zone."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _utc(value)
    return value.isoformat() if value else None


def _account_settings(app: GitHubApp) -> str:
    if app.owner_type == "Organization":
        return f"{GITHUB}/organizations/{app.owner}/settings"
    return f"{GITHUB}/settings"


def manage_url(app: GitHubApp) -> str:
    """where an admin chooses the installation's repositories on github."""
    return f"{_account_settings(app)}/installations/{app.installation_id}"


def app_settings_url(app: GitHubApp) -> str:
    """where the app's owner deletes the app itself on github."""
    return f"{_account_settings(app)}/apps/{app.slug}"


class GitHubService:
    """the workspace's own read-only github app: made through github's
    manifest flow, installed by an admin, and removed again.

    connecting is a setting an admin makes, not a change. the private key and
    the webhook secret leave github once, in the manifest's conversion, and
    are kept sealed; nothing qbrix returns carries them.
    """

    def __init__(
        self,
        *,
        settings: ProxySettings,
        client: GitHubClient | None = None,
        clock: Callable[[], datetime] = _now,
    ):
        self._settings = settings
        self._box = SecretBox(settings.derived_key(BOX_LABEL))
        self._states = StateSigner(settings.derived_key(STATE_LABEL))
        self._client = client or GitHubClient()
        self._clock = clock
        self._tokens: VTTLCache = VTTLCache(maxsize=1024)
        self._repositories: TTLCache = TTLCache(maxsize=1024, ttl=REPOSITORIES_TTL_SEC)

    @property
    def _origin(self) -> str:
        return self._settings.public_origin

    @property
    def settings_page(self) -> str:
        return f"{self._settings.console_origin}/next/settings/workspace/github"

    def events_url(self, events_token: str) -> str:
        return f"{self._origin}/api/v1/github/events/{events_token}"

    async def read(self, tenant_id: str, *, admin_id: str | None = None) -> dict:
        """the workspace's connection as every role sees it. an admin also
        gets the link that finishes an installation left half done."""
        async with get_session() as session:
            app = await GitHubAppRepository(session, tenant_id).get()
            people = await People.load(
                session, tenant_id, [app.created_by if app else ""]
            )
        reachable, note = self._reach(app)
        found: dict = {
            "connected": bool(app and app.installation_id),
            "reachable": reachable,
            "reach_note": note,
            "repositories": [],
        }
        if app is None:
            return found
        found.update(
            owner=app.owner,
            set_up_by={"id": app.created_by, "name": people.name(app.created_by)},
            at=_iso(app.created_at),
        )
        if app.installation_id is None:
            if admin_id is not None:
                found["install_url"] = self._install_url(
                    app.slug,
                    state=self._sign(
                        State(
                            tenant_id=tenant_id,
                            user_id=admin_id,
                            step="installed",
                            events_token=app.events_token,
                        )
                    ),
                )
            return found
        found["manage_url"] = manage_url(app)
        found["repositories"] = await self._repository_list(app)
        return found

    def _reach(self, app: GitHubApp | None) -> tuple[bool | None, str | None]:
        """whether github reaches the install: false when the address rules it
        out or the installation went a minute without an event, true once an
        event arrived, and None while nothing says either way."""
        reason = unreachable_reason(self._origin)
        if reason is not None:
            return False, reason
        if app is None:
            return None, None
        if app.last_event_at is not None:
            return True, None
        installed_at = _utc(app.installed_at)
        if installed_at is not None and self._clock() - installed_at >= REACH_WINDOW:
            return False, (
                f"GitHub hasn't reached {host_of(self._origin)} since the app was "
                "installed. Check that the address is public and that nothing "
                "in front of qbrix blocks /api/v1/github/events."
            )
        return None, None

    async def _repository_list(self, app: GitHubApp) -> list[dict] | None:
        """the repositories the installation may see, or None when github
        couldn't be asked."""
        names = self._repositories.get(app.installation_id)
        if names is None:
            try:
                token = await self._installation_token(app)
                names = await self._client.repositories(token)
            except (GitHubUnavailableError, SecretUnreadableError) as e:
                logger.warning(
                    f"github repositories unavailable in tenant {app.tenant_id}: {e}"
                )
                return None
            self._repositories.insert(app.installation_id, names)
        return [
            {"full_name": name, "mentions": 0, "last_mention": None} for name in names
        ]

    async def _installation_token(self, app: GitHubApp) -> str:
        cached = self._tokens.get(app.installation_id)
        if cached is not None:
            return cached
        issued = await self._client.installation_token(
            self._app_jwt(app), app.installation_id
        )
        ttl = (issued.expires_at - self._clock() - TOKEN_MARGIN).total_seconds()
        if ttl > 0:
            self._tokens.insert(app.installation_id, issued.token, ttl=ttl)
        return issued.token

    def _app_jwt(self, app: GitHubApp) -> str:
        private_key = self._box.open(
            app.private_key_ciphertext,
            tenant_id=app.tenant_id,
            purpose=PRIVATE_KEY,
            row_id=app.id,
        )
        return app_jwt(app.app_id, private_key, now=self._clock().timestamp())

    async def connect(
        self, tenant_id: str, organisation: str | None, *, actor: Actor
    ) -> dict:
        """the form the console posts to github to create the workspace's app,
        already filled in with this install's addresses."""
        async with get_session() as session:
            repo = GitHubAppRepository(session, tenant_id)
            app = await repo.get()
            if app is not None and app.installation_id is not None:
                raise GitHubAlreadyConnectedError("github is already connected")
            slug = await repo.workspace_slug()
        events_token = secrets.token_urlsafe(24)
        state = self._sign(
            State(
                tenant_id=tenant_id,
                user_id=actor.user_id,
                step="created",
                events_token=events_token,
            )
        )
        account = f"/organizations/{organisation}" if organisation else ""
        logger.info(
            f"github connect started in tenant {tenant_id} by {actor.user_id}"
            + (f" for organisation {organisation}" if organisation else "")
        )
        return {
            "form_action": f"{GITHUB}{account}/settings/apps/new?"
            + urlencode({"state": state}),
            "manifest": self._manifest(slug, events_token),
        }

    def _manifest(self, workspace_slug: str, events_token: str) -> dict:
        return {
            "name": f"qbrix-{workspace_slug}"[:APP_NAME_MAX],
            "url": self._settings.console_origin,
            "description": (
                "Links pull requests and commits that mention a qbrix loop to "
                "its history. qbrix reads their titles, descriptions, branch "
                "names, authors and states, never files, and writes nothing."
            ),
            "hook_attributes": {"url": self.events_url(events_token), "active": True},
            "redirect_url": f"{self._origin}/api/v1/github/created",
            "setup_url": f"{self._origin}/api/v1/github/installed",
            "setup_on_update": False,
            "public": False,
            "default_permissions": dict(PERMISSIONS),
            "default_events": list(EVENTS),
        }

    async def created(self, code: str, state: str) -> str:
        """turn github's code into the workspace's app, and return where the
        admin installs it."""
        found = self._verify(state, step="created")
        conversion = await self._client.convert_manifest(code)
        async with get_session() as session:
            repo = GitHubAppRepository(session, found.tenant_id)
            app = await repo.get()
            if app is not None and app.installation_id is not None:
                raise GitHubAlreadyConnectedError("github is already connected")
            if app is None:
                app = GitHubApp(id=uuid4().hex, tenant_id=found.tenant_id)
                repo.add(app)
            else:
                logger.info(
                    f"github app {app.slug} in tenant {found.tenant_id} was never "
                    f"installed and is replaced by {conversion.slug}; it stays on "
                    "github until its owner deletes it"
                )
            self._store(app, conversion, found)
            await session.flush()
        logger.info(
            f"github app {conversion.slug} created in tenant {found.tenant_id} "
            f"by {found.user_id}"
        )
        return self._install_url(
            conversion.slug,
            state=self._sign(
                State(
                    tenant_id=found.tenant_id,
                    user_id=found.user_id,
                    step="installed",
                    events_token=found.events_token,
                )
            ),
        )

    def _store(self, app: GitHubApp, conversion: Conversion, state: State) -> None:
        app.app_id = conversion.app_id
        app.slug = conversion.slug
        app.client_id = conversion.client_id
        app.owner = conversion.owner
        app.owner_type = conversion.owner_type
        app.events_token = state.events_token
        app.installation_id = None
        app.installed_at = None
        app.last_event_at = None
        app.created_by = state.user_id
        app.created_at = self._clock()
        app.private_key_ciphertext = self._box.seal(
            conversion.private_key,
            tenant_id=app.tenant_id,
            purpose=PRIVATE_KEY,
            row_id=app.id,
        )
        app.webhook_secret_ciphertext = self._box.seal(
            conversion.webhook_secret,
            tenant_id=app.tenant_id,
            purpose=WEBHOOK_SECRET,
            row_id=app.id,
        )

    def _install_url(self, slug: str, *, state: str) -> str:
        return f"{GITHUB}/apps/{slug}/installations/new?" + urlencode({"state": state})

    async def installed(self, installation_id: int, state: str) -> None:
        """record the installation github's setup page came back with, once
        github confirms it belongs to the workspace's app."""
        found = self._verify(state, step="installed")
        async with get_session() as session:
            app = await GitHubAppRepository(session, found.tenant_id).get()
        if app is None or app.events_token != found.events_token:
            raise GitHubStateError("the app this state was made for is gone")
        if await self._client.installation(self._app_jwt(app), installation_id) is None:
            raise GitHubStateError("the installation isn't the workspace app's")
        async with get_session() as session:
            app = await GitHubAppRepository(session, found.tenant_id).get()
            if app is None or app.events_token != found.events_token:
                raise GitHubStateError("the app this state was made for is gone")
            self._install(app, installation_id)
        logger.info(
            f"github app {app.slug} installed in tenant {found.tenant_id} "
            f"by {found.user_id}"
        )

    def _install(self, app: GitHubApp, installation_id: int) -> None:
        if app.installation_id != installation_id:
            app.installation_id = installation_id
            app.installed_at = self._clock()

    async def disconnect(self, tenant_id: str, *, actor: Actor) -> dict:
        """remove the installation on github, then the credentials here. the
        app stays on github, and the result says where its owner deletes it.
        mentions already in history stay."""
        async with get_session() as session:
            app = await GitHubAppRepository(session, tenant_id).get()
        if app is None:
            raise GitHubNotConnectedError("the workspace hasn't connected github")
        if app.installation_id is not None:
            try:
                token = self._app_jwt(app)
            except SecretUnreadableError:
                logger.warning(
                    f"github private key unreadable in tenant {tenant_id}; "
                    "removing the credentials without uninstalling"
                )
            else:
                await self._client.delete_installation(token, app.installation_id)
            self._forget(app.installation_id)
        async with get_session() as session:
            await GitHubAppRepository(session, tenant_id).delete()
        logger.info(
            f"github app {app.slug} disconnected in tenant {tenant_id} "
            f"by {actor.user_id}"
        )
        return {"app_settings_url": app_settings_url(app)}

    async def event(
        self, events_token: str, headers: Mapping[str, str], body: bytes
    ) -> str:
        """take one event github sent to the app's address, once its signature
        checks out, and return its name. any event shows github reaches the
        install; installation events keep the installation current."""
        async with get_session() as session:
            app = await by_events_token(session, events_token)
            if app is None:
                raise GitHubNotConnectedError("no app receives events here")
            try:
                secret = self._box.open(
                    app.webhook_secret_ciphertext,
                    tenant_id=app.tenant_id,
                    purpose=WEBHOOK_SECRET,
                    row_id=app.id,
                )
            except SecretUnreadableError as e:
                raise GitHubSignatureError("the webhook secret can't be read") from e
            if not _signed(secret, body, headers.get("x-hub-signature-256", "")):
                raise GitHubSignatureError("the event isn't signed by the app")
            name = headers.get("x-github-event", "")
            app.last_event_at = self._clock()
            if name == "installation":
                self._installation_event(app, json.loads(body))
        return name

    def _installation_event(self, app: GitHubApp, payload: dict) -> None:
        installation_id = payload["installation"]["id"]
        action = payload.get("action")
        if action == "created":
            self._install(app, installation_id)
            logger.info(f"github app {app.slug} installed in tenant {app.tenant_id}")
        elif action == "deleted" and app.installation_id == installation_id:
            self._forget(installation_id)
            app.installation_id = None
            app.installed_at = None
            logger.info(f"github app {app.slug} uninstalled in tenant {app.tenant_id}")

    def _forget(self, installation_id: int) -> None:
        self._tokens.pop(installation_id, None)
        self._repositories.pop(installation_id, None)

    def _sign(self, state: State) -> str:
        return self._states.sign(state, now=self._clock().timestamp())

    def _verify(self, token: str, *, step: str) -> State:
        return self._states.verify(token, step=step, now=self._clock().timestamp())


def _signed(secret: str, body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)

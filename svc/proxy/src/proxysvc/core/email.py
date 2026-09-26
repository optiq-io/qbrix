from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from html import escape
from typing import Protocol

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    """delivers one already-rendered message."""

    enabled: bool

    async def send(self, to: str, subject: str, html: str) -> None: ...


class NullSender:
    """logs the link instead of sending it.

    the only transport a self-hoster gets for free, so the links stay readable
    in the proxy log rather than disappearing.
    """

    enabled = False

    async def send(self, to: str, subject: str, html: str) -> None:
        logger.info(f"email not configured — would send '{subject}' to {to}")


class ResendSender:
    enabled = True

    def __init__(self, api_key: str, from_email: str):
        try:
            import resend
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "the resend email provider is selected but the resend package "
                "is not installed; install proxysvc[resend]"
            ) from e
        resend.api_key = api_key
        self._resend = resend
        self._from = from_email

    async def send(self, to: str, subject: str, html: str) -> None:
        await asyncio.to_thread(
            self._resend.Emails.send,
            {"from": self._from, "to": to, "subject": subject, "html": html},
        )


class SMTPSender:
    enabled = True

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        starttls: bool,
        from_email: str,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._starttls = starttls
        self._from = from_email

    async def send(self, to: str, subject: str, html: str) -> None:
        message = EmailMessage()
        message["From"] = self._from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(html, subtype="html")
        await asyncio.to_thread(self._deliver, message)

    def _deliver(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._host, self._port, timeout=30) as client:
            if self._starttls:
                client.starttls()
            if self._username:
                client.login(self._username, self._password)
            client.send_message(message)


class EmailService:
    """renders the transactional emails and hands them to a sender."""

    def __init__(self, sender: EmailSender):
        self._sender = sender

    @property
    def enabled(self) -> bool:
        return self._sender.enabled

    async def _send(self, to: str, subject: str, html: str) -> None:
        # a line break in a subject would start a new header
        await self._sender.send(to, " ".join(subject.splitlines()), html)

    async def send_password_reset(self, to: str, reset_url: str) -> None:
        if not self._sender.enabled:
            logger.info(f"email not configured — password reset url: {reset_url}")
            return

        await self._send(
            to,
            "Reset your qbrix password",
            f"<p>You requested a password reset for your qbrix account.</p>"
            f'<p><a href="{escape(reset_url)}">Click here to reset your password</a></p>'
            f"<p>This link expires in 15 minutes. If you didn't request this, ignore this email.</p>",
        )

    async def send_email_verification(self, to: str, verify_url: str) -> None:
        if not self._sender.enabled:
            logger.info(f"email not configured — email verification url: {verify_url}")
            return

        await self._send(
            to,
            "Verify your qbrix email",
            f"<p>Welcome to qbrix! Please confirm your email address to activate your account.</p>"
            f'<p><a href="{escape(verify_url)}">Click here to verify your email</a></p>'
            f"<p>This link expires in 24 hours. If you didn't create a qbrix account, ignore this email.</p>",
        )

    async def send_workspace_invite(
        self,
        to: str,
        invite_url: str,
        inviter_name: str,
        workspace_name: str,
        expires_at: datetime,
    ) -> None:
        if not self._sender.enabled:
            logger.info(f"email not configured — workspace invite url: {invite_url}")
            return

        expiry = expires_at.strftime("%B %-d, %Y")
        await self._send(
            to,
            f"{inviter_name} invited you to {workspace_name} on qbrix",
            f"<p>{escape(inviter_name)} invited you to join the "
            f"<strong>{escape(workspace_name)}</strong> workspace on qbrix.</p>"
            f'<p><a href="{escape(invite_url)}">Click here to accept the invite</a></p>'
            f"<p>This invite expires on {expiry}. "
            f"If you weren't expecting this, ignore this email.</p>",
        )


def create_email_sender(settings) -> EmailSender:
    """resolve PROXY_EMAIL_PROVIDER into a sender.

    an explicitly named provider that is not configured is a boot failure: a
    deployment that asked for smtp and silently fell back to logging links
    would look healthy while locking every new user out.
    """
    provider = settings.email_provider
    if provider == "auto":
        if settings.resend_api_key:
            provider = "resend"
        elif settings.smtp_host:
            provider = "smtp"
        else:
            provider = "none"

    if provider == "resend":
        if not settings.resend_api_key:
            raise RuntimeError(
                "PROXY_EMAIL_PROVIDER=resend requires PROXY_RESEND_API_KEY"
            )
        logger.info("email provider: resend")
        return ResendSender(settings.resend_api_key, settings.email_from)

    if provider == "smtp":
        if not settings.smtp_host:
            raise RuntimeError("PROXY_EMAIL_PROVIDER=smtp requires PROXY_SMTP_HOST")
        logger.info(f"email provider: smtp ({settings.smtp_host}:{settings.smtp_port})")
        return SMTPSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            starttls=settings.smtp_starttls,
            from_email=settings.email_from,
        )

    logger.warning(
        "no email provider configured — new accounts are auto-verified and "
        "reset/invite links are written to this log. set PROXY_SMTP_HOST or "
        "PROXY_RESEND_API_KEY to send mail"
    )
    return NullSender()

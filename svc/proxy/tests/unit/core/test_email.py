"""provider resolution and delivery for the transactional email layer."""

from __future__ import annotations

import smtplib
from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from proxysvc.config import ProxySettings
from proxysvc.core.email import EmailService
from proxysvc.core.email import NullSender
from proxysvc.core.email import SMTPSender
from proxysvc.core.email import create_email_sender


class TestProviderResolution:
    def test_auto_with_nothing_configured_is_none(self):
        sender = create_email_sender(ProxySettings())

        assert isinstance(sender, NullSender)
        assert sender.enabled is False

    def test_auto_prefers_resend_over_smtp(self):
        settings = ProxySettings(resend_api_key="re_x", smtp_host="localhost")

        with patch.dict("sys.modules", {"resend": MagicMock()}):
            sender = create_email_sender(settings)

        assert type(sender).__name__ == "ResendSender"

    def test_auto_falls_back_to_smtp(self):
        sender = create_email_sender(ProxySettings(smtp_host="localhost"))

        assert isinstance(sender, SMTPSender)

    def test_explicit_smtp_without_a_host_fails_at_boot(self):
        with pytest.raises(RuntimeError, match="PROXY_SMTP_HOST"):
            create_email_sender(ProxySettings(email_provider="smtp"))

    def test_explicit_resend_without_a_key_fails_at_boot(self):
        with pytest.raises(RuntimeError, match="PROXY_RESEND_API_KEY"):
            create_email_sender(ProxySettings(email_provider="resend"))

    def test_explicit_none_ignores_a_configured_provider(self):
        settings = ProxySettings(email_provider="none", smtp_host="localhost")

        assert isinstance(create_email_sender(settings), NullSender)


class TestSMTPDelivery:
    async def test_starttls_and_login_are_applied(self):
        client = MagicMock()
        sender = SMTPSender(
            host="mail.example.com",
            port=587,
            username="user",
            password="pw",
            starttls=True,
            from_email="qbrix <noreply@example.com>",
        )

        with patch.object(smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = client
            await sender.send("to@example.com", "Subject", "<p>body</p>")

        smtp.assert_called_once_with("mail.example.com", 587, timeout=30)
        client.starttls.assert_called_once()
        client.login.assert_called_once_with("user", "pw")
        message = client.send_message.call_args.args[0]
        assert message["To"] == "to@example.com"
        assert message["Subject"] == "Subject"
        assert message.get_content_type() == "text/html"

    async def test_anonymous_relay_does_not_log_in(self):
        client = MagicMock()
        sender = SMTPSender(
            host="localhost",
            port=1025,
            username="",
            password="",
            starttls=False,
            from_email="qbrix <noreply@localhost>",
        )

        with patch.object(smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = client
            await sender.send("to@example.com", "Subject", "<p>body</p>")

        client.starttls.assert_not_called()
        client.login.assert_not_called()
        client.send_message.assert_called_once()


class TestEmailService:
    async def test_unconfigured_service_reports_disabled_and_sends_nothing(self):
        sender = NullSender()
        sender.send = MagicMock()
        service = EmailService(sender)

        await service.send_email_verification("to@example.com", "https://x/verify")
        await service.send_password_reset("to@example.com", "https://x/reset")
        await service.send_workspace_invite(
            to="to@example.com",
            invite_url="https://x/invite",
            inviter_name="Ada",
            workspace_name="Acme",
            expires_at=datetime.now(timezone.utc),
        )

        assert service.enabled is False
        sender.send.assert_not_called()

    async def test_every_message_goes_through_the_sender(self, recording_sender):
        service = EmailService(recording_sender)

        await service.send_email_verification("to@example.com", "https://x/verify")
        await service.send_password_reset("to@example.com", "https://x/reset")
        await service.send_workspace_invite(
            to="to@example.com",
            invite_url="https://x/invite",
            inviter_name="Ada",
            workspace_name="Acme",
            expires_at=datetime.now(timezone.utc),
        )

        assert service.enabled is True
        assert [subject for _, subject, _ in recording_sender.sent] == [
            "Verify your qbrix email",
            "Reset your qbrix password",
            "Ada invited you to Acme on qbrix",
        ]
        assert "https://x/verify" in recording_sender.sent[0][2]

    async def test_invite_names_are_text_not_markup(self, recording_sender):
        service = EmailService(recording_sender)

        await service.send_workspace_invite(
            to="to@example.com",
            invite_url="https://x/invite?token=a&b",
            inviter_name='<a href="https://x">⚡bonus⚡</a>',
            workspace_name="<img src=x>",
            expires_at=datetime.now(timezone.utc),
        )

        [(_, _, html)] = recording_sender.sent
        assert "&lt;a href=&quot;https://x&quot;&gt;⚡bonus⚡&lt;/a&gt;" in html
        assert "<strong>&lt;img src=x&gt;</strong>" in html
        assert 'href="https://x/invite?token=a&amp;b"' in html

    @pytest.mark.parametrize("breaker", ["\r\n", "\n", "\r", " "])
    async def test_a_name_cannot_break_the_subject_line(
        self, recording_sender, breaker
    ):
        service = EmailService(recording_sender)

        await service.send_workspace_invite(
            to="to@example.com",
            invite_url="https://x/invite",
            inviter_name=f"Ada{breaker}Bcc: victim@example.com",
            workspace_name="Acme",
            expires_at=datetime.now(timezone.utc),
        )

        [(_, subject, _)] = recording_sender.sent
        assert subject == "Ada Bcc: victim@example.com invited you to Acme on qbrix"

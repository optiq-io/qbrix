import os

# the suite runs as the cloud edition with analytics unless the caller picks
# otherwise, so `PROXY_EE_ENABLED=false pytest` exercises the oss edition. set
# before proxysvc.config is imported, since the http app mounts routers off it.
os.environ.setdefault("PROXY_EE_ENABLED", "true")
os.environ.setdefault("PROXY_ANALYTICS_ENABLED", "true")
# the suite's baseline is the cloud's open signup; the self-host modes have
# their own tests, which set the mode themselves.
os.environ.setdefault("PROXY_SIGNUP_MODE", "open")

import pytest


class RecordingSender:
    """an email sender that delivers nowhere but counts as configured.

    the distinction matters: an unconfigured deployment auto-verifies new
    accounts, so a test that wants the verification flow needs a sender that
    reports itself enabled.
    """

    enabled = True

    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, html: str) -> None:
        self.sent.append((to, subject, html))


@pytest.fixture
def next_enabled(monkeypatch) -> None:
    """switch qbrix next on for one test; the suite otherwise runs today's product.

    it flips the setting only: routes mount while the app module imports, so a
    test of a next route boots its own process, as integration/test_oss_boot.py
    does.
    """
    import proxysvc.config

    monkeypatch.setattr(proxysvc.config.settings, "next_enabled", True)


@pytest.fixture
def recording_sender() -> RecordingSender:
    return RecordingSender()

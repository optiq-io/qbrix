"""unit tests for the proxy's /info endpoint.

invariants verified:
  - /info and the openapi schema report the installed proxysvc version, so a
    release bump reaches them without a code change
"""

from __future__ import annotations

from importlib.metadata import version

from proxysvc.transport.http.app import app
from proxysvc.transport.http.app import info


async def test_info_reports_the_package_version() -> None:
    body = await info()

    assert body["version"] == version("proxysvc")
    assert app.version == version("proxysvc")

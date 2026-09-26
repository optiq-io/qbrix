from collections.abc import Iterator

import pytest

from proxysvc.config import settings
from proxysvc.ee.billing.announcer import NullTenantAnnouncer
from proxysvc.ee.billing.router import set_billing_service
from proxysvc.ee.billing.service import BillingService

from svc.proxy.tests.integration.http.conftest import app_with_db  # noqa: F401
from svc.proxy.tests.integration.http.conftest import client  # noqa: F401
from svc.proxy.tests.integration.http.conftest import fake_redis_client  # noqa: F401
from svc.proxy.tests.integration.http.conftest import tenant_a  # noqa: F401
from svc.proxy.tests.integration.http.conftest import tenant_b  # noqa: F401
from svc.proxy.tests.integration.http.conftest import wired_app  # noqa: F401
from svc.proxy.tests.unit.conftest import mock_cortex_client  # noqa: F401
from svc.proxy.tests.unit.conftest import mock_feedback_publisher  # noqa: F401
from svc.proxy.tests.unit.conftest import mock_motor_client  # noqa: F401
from svc.proxy.tests.unit.conftest import mock_redis  # noqa: F401
from svc.proxy.tests.unit.conftest import proxy_settings  # noqa: F401

collect_ignore_glob = [] if settings.ee_enabled else ["*"]


@pytest.fixture
def billing(wired_app) -> Iterator[BillingService]:  # noqa: F811
    """a per-test billing service behind the billing router, announcing nowhere.

    per-test so its usage cache starts empty and cannot bleed between tests.
    """
    service = BillingService(announcer=NullTenantAnnouncer())
    set_billing_service(service)
    yield service
    set_billing_service(None)  # type: ignore[arg-type]

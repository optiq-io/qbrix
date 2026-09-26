"""the cloud edition mounts billing — which is what makes its absence mean something.

without this, `test_oss_boot.py` would keep passing if the billing router were
deleted outright.
"""

from __future__ import annotations

from svc.proxy.tests.integration.test_oss_boot import BILLING_PREFIX
from svc.proxy.tests.integration.test_oss_boot import boot
from svc.proxy.tests.integration.test_oss_boot import mounted


class TestCloudBoot:
    def test_billing_is_mounted_and_the_plugin_is_imported(self):
        cloud = boot(ee=True, analytics=True)

        assert mounted(cloud["routes"], BILLING_PREFIX)
        assert "proxysvc.ee" in cloud["loaded"]
        assert "stripe" in cloud["loaded"]

"""the boot check for stripe prices the proxy cannot resolve."""

from __future__ import annotations

from unittest.mock import patch

import proxysvc.ee as ee_module
from proxysvc.config import ProxySettings


def _settings(**prices) -> ProxySettings:
    return ProxySettings(
        stripe_secret_key="sk_test_x",
        stripe_price_id_starter=prices.get("starter", "price_s"),
        stripe_price_id_growth=prices.get("growth", "price_g"),
        stripe_price_id_scale=prices.get("scale", "price_sc"),
        stripe_price_id_enterprise=prices.get("enterprise", "price_e"),
    )


def test_an_unsold_tier_is_a_warning_not_an_error():
    with patch.object(ee_module, "logger") as logger:
        ee_module._verify_billing_config(_settings(enterprise=""))

    logger.error.assert_not_called()
    [message] = logger.warning.call_args.args
    assert "PROXY_STRIPE_PRICE_ID_ENTERPRISE" in message


def test_every_price_configured_says_nothing():
    with patch.object(ee_module, "logger") as logger:
        ee_module._verify_billing_config(_settings())

    logger.warning.assert_not_called()
    logger.error.assert_not_called()


def test_without_stripe_there_is_nothing_to_check():
    with patch.object(ee_module, "logger") as logger:
        ee_module._verify_billing_config(ProxySettings(stripe_secret_key=""))

    logger.warning.assert_not_called()

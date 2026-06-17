#!/usr/bin/env python3
import os
import unittest
from unittest.mock import patch

from src.assert_env import load_config_from_env


def _base_env() -> dict:
    return {
        "CURRENCIES": "BTC,ETH",
        "DATA_AREA_ROOT_DIR": "/tmp/cryptohunk_data",
        "CURRENCY_HISTORY_PERIOD": "1h",
        "CURRENCY_HISTORY_NOF_ELEMENTS": "300",
        "BINANCE_KEY": "live_key",
        "BINANCE_SECRET": "live_secret",
        "BINANCE_TRADING_URL": "https://api.binance.com/api/v3/order",
    }


class TestAssertEnv(unittest.TestCase):
    def test_default_env_is_live_and_uses_live_profile(self):
        with patch.dict(os.environ, _base_env(), clear=True):
            cfg = load_config_from_env()

        self.assertEqual(cfg.binance_api_env, "live")
        self.assertEqual(cfg.binance_key, "live_key")
        self.assertEqual(cfg.binance_secret, "live_secret")
        self.assertEqual(cfg.binance_base_url, "https://api.binance.com")
        self.assertEqual(cfg.binance_trading_url, "https://api.binance.com/api/v3/order")

    def test_testnet_env_uses_testnet_profile(self):
        env = _base_env()
        env.update(
            {
                "BINANCE_API_ENV": "testnet",
                "BINANCE_TESTNET_KEY": "testnet_key",
                "BINANCE_TESTNET_SECRET": "testnet_secret",
                "BINANCE_TRADING_TESTNET_URL": "https://testnet.binance.vision/api/v3/order",
            }
        )

        with patch.dict(os.environ, env, clear=True):
            cfg = load_config_from_env()

        self.assertEqual(cfg.binance_api_env, "testnet")
        self.assertEqual(cfg.binance_key, "testnet_key")
        self.assertEqual(cfg.binance_secret, "testnet_secret")
        self.assertEqual(cfg.binance_base_url, "https://testnet.binance.vision")
        self.assertEqual(cfg.binance_trading_url, "https://testnet.binance.vision/api/v3/order")

    def test_missing_non_selected_profile_does_not_fail(self):
        env = _base_env()
        env["BINANCE_API_ENV"] = "live"

        with patch.dict(os.environ, env, clear=True):
            cfg = load_config_from_env()

        self.assertEqual(cfg.binance_api_env, "live")

    def test_missing_selected_testnet_profile_fails(self):
        env = _base_env()
        env["BINANCE_API_ENV"] = "testnet"

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(EnvironmentError) as ctx:
                load_config_from_env()

        self.assertIn("BINANCE_TESTNET_SECRET", str(ctx.exception))
        self.assertIn("BINANCE_TESTNET_KEY", str(ctx.exception))
        self.assertIn("BINANCE_TRADING_TESTNET_URL", str(ctx.exception))

    def test_invalid_binance_api_env_fails(self):
        env = _base_env()
        env["BINANCE_API_ENV"] = "paper"

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(EnvironmentError) as ctx:
                load_config_from_env()

        self.assertIn("BINANCE_API_ENV", str(ctx.exception))

    def test_base_url_override_is_profile_specific(self):
        env = _base_env()
        env.update(
            {
                "BINANCE_API_ENV": "testnet",
                "BINANCE_TESTNET_KEY": "testnet_key",
                "BINANCE_TESTNET_SECRET": "testnet_secret",
                "BINANCE_TESTNET_BASE_URL": "https://example.testnet",
                "BINANCE_TRADING_TESTNET_URL": "https://example.testnet/api/v3/order",
            }
        )

        with patch.dict(os.environ, env, clear=True):
            cfg = load_config_from_env()

        self.assertEqual(cfg.binance_base_url, "https://example.testnet")


if __name__ == "__main__":
    unittest.main()

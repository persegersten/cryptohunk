#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.collect_data import CollectData
from src.config import Config


def _cfg(data_root: str) -> Config:
    return Config(
        currencies=["BTC"],
        binance_secret="test_secret",
        binance_key="test_key",
        binance_base_url="https://api.binance.com",
        binance_currency_history_endpoint="/api/v3/klines",
        binance_exchange_info_endpoint="/api/v3/exchangeInfo",
        binance_my_trades_endpoint="/api/v3/myTrades",
        binance_trading_url="https://api.binance.com/api/v3/order",
        dry_run=True,
        data_area_root_dir=data_root,
        currency_history_period="1h",
        currency_history_nof_elements=300,
        trade_threshold=100.0,
        take_profit_percentage=10.0,
        stop_loss_percentage=6.0,
        allowed_quote_assets=["USDC"],
        ftp_host=None,
        ftp_dir=None,
        ftp_username=None,
        ftp_password=None,
        ftp_html_regexp=None,
        raw_env={},
    )


class TestCollectData(unittest.TestCase):
    def test_collect_currency_rate_history_uses_usdc_symbol(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            response = Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = [
                [
                    1_700_000_000_000,
                    "40000",
                    "40100",
                    "39900",
                    "40050",
                    "1.0",
                    1_700_000_003_599,
                    "40050",
                    10,
                    "0.5",
                    "20025",
                ]
            ]

            with patch("src.collect_data.requests.get", return_value=response) as mock_get:
                CollectData(_cfg(tmpdir)).collect_currency_rate_history()

            requested_params = mock_get.call_args.kwargs["params"]
            self.assertEqual(requested_params["symbol"], "BTCUSDC")
            self.assertTrue((Path(tmpdir) / "history" / "BTC_history.csv").exists())

    def test_collect_trade_history_filters_to_usdc_symbols(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = CollectData(_cfg(tmpdir))
            collector._get_exchange_info = Mock(
                return_value={
                    "symbols": [
                        {"symbol": "BTCUSDC", "baseAsset": "BTC", "quoteAsset": "USDC"},
                        {"symbol": "BTCFDUSD", "baseAsset": "BTC", "quoteAsset": "FDUSD"},
                    ]
                }
            )
            collector._get_trades_for_symbol = Mock(return_value=[])

            collector.collect_trade_history()

            collector._get_trades_for_symbol.assert_called_once_with("BTCUSDC")


if __name__ == "__main__":
    unittest.main()

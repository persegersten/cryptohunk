#!/usr/bin/env python3
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.config import Config
from src.summarize_portfolio import summarize_portfolio


def _cfg(data_root: str) -> Config:
    return Config(
        currencies=["BNB"],
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


class TestSummarizePortfolio(unittest.TestCase):
    def test_summary_uses_usdc_quote_asset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            portfolio_dir = data_root / "portfolio"
            trades_dir = data_root / "trades"
            portfolio_dir.mkdir()
            trades_dir.mkdir()

            with open(portfolio_dir / "portfolio.json", "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "balances": {
                            "BNB": {"total": "2.0"},
                            "USDC": {"total": "15.0"},
                        }
                    },
                    f,
                )

            with open(trades_dir / "trades.json", "w", encoding="utf-8") as f:
                json.dump(
                    [{"symbol": "BNBUSDC", "isBuyer": True, "price": "300", "time": 1}],
                    f,
                )

            response = Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = {"price": "310"}

            with patch("src.summarize_portfolio.requests.get", return_value=response) as mock_get:
                summarize_portfolio(_cfg(tmpdir))

            requested_symbols = [call.kwargs["params"]["symbol"] for call in mock_get.call_args_list]
            self.assertEqual(requested_symbols, ["BNBUSDC"])

            with open(data_root / "summarised" / "portfolio.csv", newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

            currencies = {row["currency"] for row in rows}
            self.assertEqual(currencies, {"BNB", "USDC"})


if __name__ == "__main__":
    unittest.main()

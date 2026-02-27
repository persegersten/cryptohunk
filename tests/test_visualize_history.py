#!/usr/bin/env python3
"""
Tester för VisualizeHistory-modulen.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config
from src.visualize_history import VisualizeHistory


def _make_cfg(data_root: str) -> Config:
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
        currency_history_nof_elements=50,
        trade_threshold=10.0,
        take_profit_percentage=10.0,
        stop_loss_percentage=6.0,
        allowed_quote_assets=["USDT"],
        ftp_host=None,
        ftp_dir=None,
        ftp_username=None,
        ftp_password=None,
        ftp_html_regexp=None,
        raw_env={},
    )


def _create_history_csv(history_dir: Path, currency: str, n: int = 50) -> None:
    """Skapa en minimal kurshistorikfil för testning."""
    base_ms = 1_700_000_000_000  # 2023-11-14T22:13:20Z ungefär
    interval_ms = 3_600_000
    prices = [40000 + i * 10 for i in range(n)]
    data = {
        "Open_Time_ms": [base_ms + i * interval_ms for i in range(n)],
        "Open": prices,
        "High": [p * 1.005 for p in prices],
        "Low": [p * 0.995 for p in prices],
        "Close": prices,
        "Volume": [100.0] * n,
        "Close_Time_ms": [base_ms + i * interval_ms + interval_ms - 1 for i in range(n)],
        "Quote_Asset_Volume": [4_000_000.0] * n,
        "Number_of_Trades": [1000] * n,
        "Taker_Buy_Base_Asset_Volume": [50.0] * n,
        "Taker_Buy_Quote_Asset_Volume": [2_000_000.0] * n,
    }
    df = pd.DataFrame(data)
    history_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(history_dir / f"{currency}_history.csv", index=False)


def _create_trades_json(trades_dir: Path, trades: list) -> None:
    trades_dir.mkdir(parents=True, exist_ok=True)
    with open(trades_dir / "trades.json", "w", encoding="utf-8") as f:
        json.dump(trades, f)


class TestVisualizeHistory(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_root = Path(self.test_dir)
        self.cfg = _make_cfg(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # _read_history
    # ------------------------------------------------------------------

    def test_read_history_returns_dataframe(self):
        hist_dir = self.data_root / "history" / "BTC"
        _create_history_csv(hist_dir, "BTC", n=50)
        viz = VisualizeHistory(self.cfg)
        df = viz._read_history("BTC")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 50)
        self.assertIn("datetime", df.columns)

    def test_read_history_missing_file_returns_none(self):
        viz = VisualizeHistory(self.cfg)
        df = viz._read_history("NONEXISTENT")
        self.assertIsNone(df)

    # ------------------------------------------------------------------
    # _read_trades
    # ------------------------------------------------------------------

    def test_read_trades_returns_list(self):
        trades = [{"id": 1, "symbol": "BTCUSDT", "isBuyer": True, "price": "40000", "qty": "0.01",
                   "quoteQty": "400", "commission": "0.0001", "commissionAsset": "BTC",
                   "time": 1_700_003_600_000, "orderId": 100}]
        _create_trades_json(self.data_root / "trades", trades)
        viz = VisualizeHistory(self.cfg)
        result = viz._read_trades()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "BTCUSDT")

    def test_read_trades_missing_file_returns_empty_list(self):
        viz = VisualizeHistory(self.cfg)
        result = viz._read_trades()
        self.assertEqual(result, [])

    # ------------------------------------------------------------------
    # _filter_trades_for_currency
    # ------------------------------------------------------------------

    def test_filter_trades_for_currency(self):
        trades = [
            {"symbol": "BTCUSDT", "isBuyer": True, "time": 1_700_000_000_000},
            {"symbol": "ETHUSDT", "isBuyer": False, "time": 1_700_000_000_000},
            {"symbol": "BTCUSDC", "isBuyer": False, "time": 1_700_000_000_000},
        ]
        viz = VisualizeHistory(self.cfg)
        result = viz._filter_trades_for_currency(trades, "BTC")
        self.assertEqual(len(result), 2)
        for t in result:
            self.assertTrue(t["symbol"].startswith("BTC"))

    # ------------------------------------------------------------------
    # _format_trade_label
    # ------------------------------------------------------------------

    def test_format_trade_label_buy(self):
        trade = {
            "id": 42, "orderId": 99, "symbol": "BTCUSDT", "isBuyer": True,
            "price": "41000.00", "qty": "0.001", "quoteQty": "41.00",
            "commission": "0.000001", "commissionAsset": "BTC",
            "time": 1_700_003_600_000,
        }
        viz = VisualizeHistory(self.cfg)
        label = viz._format_trade_label(trade)
        self.assertIn("KÖP", label)
        self.assertIn("BTCUSDT", label)
        self.assertIn("41000.00", label)
        # Trade-ID and Order-ID should NOT appear in the popup
        self.assertNotIn("Trade-ID", label)
        self.assertNotIn("Order-ID", label)

    def test_format_trade_label_sell(self):
        trade = {
            "id": 43, "orderId": 100, "symbol": "BTCUSDT", "isBuyer": False,
            "price": "42000.00", "qty": "0.001", "quoteQty": "42.00",
            "commission": "0.042", "commissionAsset": "USDT",
            "time": 1_700_007_200_000,
        }
        viz = VisualizeHistory(self.cfg)
        label = viz._format_trade_label(trade)
        self.assertIn("SÄLJ", label)
        self.assertIn("42000.00", label)
        # Trade-ID and Order-ID should NOT appear in the popup
        self.assertNotIn("Trade-ID", label)
        self.assertNotIn("Order-ID", label)

    # ------------------------------------------------------------------
    # generate_chart
    # ------------------------------------------------------------------

    def test_generate_chart_returns_html(self):
        hist_dir = self.data_root / "history" / "BTC"
        _create_history_csv(hist_dir, "BTC", n=50)

        trades = [
            {
                "id": 1, "orderId": 10, "symbol": "BTCUSDT", "isBuyer": True,
                "price": "40100.00", "qty": "0.001", "quoteQty": "40.10",
                "commission": "0.000001", "commissionAsset": "BTC",
                "time": 1_700_003_600_000,
            },
            {
                "id": 2, "orderId": 11, "symbol": "BTCUSDT", "isBuyer": False,
                "price": "40500.00", "qty": "0.001", "quoteQty": "40.50",
                "commission": "0.04050", "commissionAsset": "USDT",
                "time": 1_700_010_800_000,
            },
        ]
        viz = VisualizeHistory(self.cfg)
        html_content = viz.generate_chart("BTC", trades)
        self.assertIsNotNone(html_content)

        self.assertIn("plotly", html_content.lower())
        # Trade data is unicode-escaped by Plotly; check for unescaped identifiers
        self.assertIn("BTCUSDT", html_content)
        # Check that both buy and sell trace names are present (unicode-escaped)
        self.assertIn('"name":"K\\u00f6p"', html_content)
        self.assertIn('"name":"S\\u00e4lj"', html_content)

    def test_generate_chart_without_trades(self):
        hist_dir = self.data_root / "history" / "BTC"
        _create_history_csv(hist_dir, "BTC", n=50)
        viz = VisualizeHistory(self.cfg)
        html_content = viz.generate_chart("BTC", [])
        self.assertIsNotNone(html_content)
        self.assertIn("plotly", html_content.lower())

    def test_generate_chart_has_rangeselector_buttons(self):
        """Verify time-range selector buttons are present in the generated HTML."""
        hist_dir = self.data_root / "history" / "BTC"
        _create_history_csv(hist_dir, "BTC", n=50)
        viz = VisualizeHistory(self.cfg)
        html_content = viz.generate_chart("BTC", [])
        self.assertIsNotNone(html_content)
        # Expected buttons (Plotly unicode-escapes Swedish characters)
        self.assertIn('"label":"Senaste veckan"', html_content)
        self.assertIn('"label":"Senaste m\\u00e5naden"', html_content)
        self.assertIn('"label":"Allt"', html_content)
        # "3 månader" button must be absent
        self.assertNotIn('"label":"3', html_content)
        self.assertIn("rangeselector", html_content.lower())

    def test_generate_chart_missing_history_returns_none(self):
        viz = VisualizeHistory(self.cfg)
        result = viz.generate_chart("BTC", [])
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def test_run_generates_all_charts(self):
        hist_dir = self.data_root / "history" / "BTC"
        _create_history_csv(hist_dir, "BTC", n=50)
        viz = VisualizeHistory(self.cfg)
        success = viz.run()
        self.assertTrue(success)
        html_file = self.data_root / "visualize" / "history_chart.html"
        self.assertTrue(html_file.exists())
        content = html_file.read_text(encoding="utf-8")
        self.assertIn("vh-tab", content)
        self.assertIn('id="tab-BTC"', content)
        self.assertIn("BTC", content)
        self.assertIn("trade-info", content)

    def test_run_returns_false_when_no_history(self):
        viz = VisualizeHistory(self.cfg)
        success = viz.run()
        self.assertFalse(success)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
Tester för VisualizeHistory-modulen.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Optional

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


def _create_history_csv(history_dir: Path, currency: str, n: int = 50, base_ms: Optional[int] = None) -> None:
    """Skapa en minimal kurshistorikfil för testning."""
    if base_ms is None:
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


def _create_portfolio_json(data_root: Path, balances: dict) -> None:
    """Create a minimal portfolio.json anchoring backward-reconstruction tests."""
    portfolio_dir = data_root / "portfolio"
    portfolio_dir.mkdir(parents=True, exist_ok=True)
    payload = {"balances": {k: {"total": str(v)} for k, v in balances.items()}}
    with open(portfolio_dir / "portfolio.json", "w", encoding="utf-8") as f:
        json.dump(payload, f)


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
        hist_dir = self.data_root / "history"
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
        # Without buy_price, no percentage change should appear
        self.assertNotIn("Förändring", label)

    def test_format_trade_label_sell_with_buy_price_profit(self):
        trade = {
            "id": 43, "orderId": 100, "symbol": "BTCUSDT", "isBuyer": False,
            "price": "42000.00", "qty": "0.001", "quoteQty": "42.00",
            "commission": "0.042", "commissionAsset": "USDT",
            "time": 1_700_007_200_000,
        }
        viz = VisualizeHistory(self.cfg)
        label = viz._format_trade_label(trade, buy_price=40000.0)
        self.assertIn("SÄLJ", label)
        self.assertIn("Förändring vs. köp", label)
        self.assertIn("+5.00%", label)

    def test_format_trade_label_sell_with_buy_price_loss(self):
        trade = {
            "id": 43, "orderId": 100, "symbol": "BTCUSDT", "isBuyer": False,
            "price": "38000.00", "qty": "0.001", "quoteQty": "38.00",
            "commission": "0.038", "commissionAsset": "USDT",
            "time": 1_700_007_200_000,
        }
        viz = VisualizeHistory(self.cfg)
        label = viz._format_trade_label(trade, buy_price=40000.0)
        self.assertIn("SÄLJ", label)
        self.assertIn("Förändring vs. köp", label)
        self.assertIn("-5.00%", label)

    # ------------------------------------------------------------------
    # generate_chart
    # ------------------------------------------------------------------

    def test_generate_chart_returns_html(self):
        hist_dir = self.data_root / "history"
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

    def test_generate_chart_sell_label_includes_pct_change_vs_buy(self):
        """Sell marker label must include percentage change vs. the preceding buy."""
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BTC", n=50)

        # Buy at 40000, sell at 42000 → +5.00 %
        trades = [
            {
                "id": 1, "orderId": 10, "symbol": "BTCUSDT", "isBuyer": True,
                "price": "40000.00", "qty": "0.001", "quoteQty": "40.00",
                "commission": "0.000001", "commissionAsset": "BTC",
                "time": 1_700_003_600_000,
            },
            {
                "id": 2, "orderId": 11, "symbol": "BTCUSDT", "isBuyer": False,
                "price": "42000.00", "qty": "0.001", "quoteQty": "42.00",
                "commission": "0.042", "commissionAsset": "USDT",
                "time": 1_700_010_800_000,
            },
        ]
        viz = VisualizeHistory(self.cfg)
        html_content = viz.generate_chart("BTC", trades)
        self.assertIsNotNone(html_content)
        # Plotly unicode-escapes non-ASCII, so check for the escaped form
        # "F\u00f6r\u00e4ndring vs. k\u00f6p" = "Förändring vs. köp"
        self.assertIn("F\\u00f6r\\u00e4ndring vs. k\\u00f6p", html_content)
        self.assertIn("+5.00%", html_content)

    def test_generate_chart_without_trades(self):
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BTC", n=50)
        viz = VisualizeHistory(self.cfg)
        html_content = viz.generate_chart("BTC", [])
        self.assertIsNotNone(html_content)
        self.assertIn("plotly", html_content.lower())

    def test_generate_chart_has_rangeselector_buttons(self):
        """Verify time-range selector buttons are present in the generated HTML."""
        hist_dir = self.data_root / "history"
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
    # _build_portfolio_performance
    # ------------------------------------------------------------------

    def test_build_portfolio_performance_returns_empty_without_trades(self):
        """Without any trades, holdings are zero → empty result."""
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BTC", n=50)
        viz = VisualizeHistory(self.cfg)
        dfs = {"BTC": viz._read_history("BTC")}
        perf = viz._build_portfolio_performance([], dfs)
        self.assertTrue(perf.empty)

    def test_build_portfolio_performance_returns_empty_without_dfs(self):
        viz = VisualizeHistory(self.cfg)
        perf = viz._build_portfolio_performance([], {})
        self.assertTrue(perf.empty)

    def test_build_portfolio_performance_first_value_is_usdc(self):
        """After a buy, first data point with holdings should equal qty × close_price in USDC."""
        hist_dir = self.data_root / "history"
        base_ms = 1_700_000_000_000
        expected_qty = 0.01
        expected_first_price = 40000  # _create_history_csv: prices[0] = 40000 + 0*10
        _create_history_csv(hist_dir, "BTC", n=50)
        # Anchor backward reconstruction to the current BTC balance from portfolio.json
        _create_portfolio_json(self.data_root, {"BTC": expected_qty})
        viz = VisualizeHistory(self.cfg)
        dfs = {"BTC": viz._read_history("BTC")}
        trades = [
            {
                "symbol": "BTCUSDT", "isBuyer": True,
                "qty": str(expected_qty), "price": str(expected_first_price),
                "time": base_ms,  # at the very first candle
            }
        ]
        perf = viz._build_portfolio_performance(trades, dfs)
        self.assertFalse(perf.empty)
        self.assertIn("datetime", perf.columns)
        self.assertIn("portfolio_value", perf.columns)
        self.assertAlmostEqual(
            perf["portfolio_value"].iloc[0],
            expected_qty * expected_first_price,
            places=4,
        )

    def test_build_portfolio_performance_sell_reduces_holdings(self):
        """After buying and then selling all, portfolio value should drop to 0."""
        hist_dir = self.data_root / "history"
        # Use an hour-aligned base so that floor('h') maps trades to exactly the
        # expected candle index (Binance klines are always on UTC-hour boundaries).
        base_ms = 1_699_999_200_000  # 2023-11-14 22:00:00 UTC
        interval_ms = 3_600_000
        _create_history_csv(hist_dir, "BTC", n=50, base_ms=base_ms)
        # After buying and then selling the full qty, the current balance is 0
        _create_portfolio_json(self.data_root, {"BTC": 0.0})
        viz = VisualizeHistory(self.cfg)
        dfs = {"BTC": viz._read_history("BTC")}
        trades = [
            {"symbol": "BTCUSDT", "isBuyer": True, "qty": "0.01",
             "price": "40000", "time": base_ms},
            # Sell all after 5 candles
            {"symbol": "BTCUSDT", "isBuyer": False, "qty": "0.01",
             "price": "40050", "time": base_ms + 5 * interval_ms},
        ]
        perf = viz._build_portfolio_performance(trades, dfs)
        # After selling all, the remaining data points should not be in the result
        # (portfolio_value == 0 is filtered out)
        last_dt = perf["datetime"].max()
        expected_last = pd.Timestamp(
            base_ms + 5 * interval_ms, unit="ms", tz="UTC"
        )
        self.assertLessEqual(last_dt, expected_last)

    def test_build_portfolio_performance_multiple_currencies(self):
        """Portfolio value sums contributions from multiple currencies."""
        base_ms = 1_700_000_000_000
        # _create_history_csv: prices[0] = 40000 + 0*10 = 40000 for both currencies
        btc_qty = 0.01
        eth_qty = 1.0
        first_price = 40000
        expected_first_value = btc_qty * first_price + eth_qty * first_price
        for currency in ["BTC", "ETH"]:
            hist_dir = self.data_root / "history"
            _create_history_csv(hist_dir, currency, n=10)
        # Anchor backward reconstruction to current balances from portfolio.json
        _create_portfolio_json(self.data_root, {"BTC": btc_qty, "ETH": eth_qty})
        viz = VisualizeHistory(self.cfg)
        dfs = {
            "BTC": viz._read_history("BTC"),
            "ETH": viz._read_history("ETH"),
        }
        trades = [
            {"symbol": "BTCUSDT", "isBuyer": True, "qty": str(btc_qty),
             "price": str(first_price), "time": base_ms},
            {"symbol": "ETHUSDT", "isBuyer": True, "qty": str(eth_qty),
             "price": str(first_price), "time": base_ms},
        ]
        perf = viz._build_portfolio_performance(trades, dfs)
        self.assertFalse(perf.empty)
        # First value should be the actual combined USDC value, not 100
        self.assertAlmostEqual(perf["portfolio_value"].iloc[0], expected_first_value, places=2)

    # ------------------------------------------------------------------
    # generate_portfolio_chart
    # ------------------------------------------------------------------

    def test_generate_portfolio_chart_returns_none_without_trades(self):
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BTC", n=50)
        viz = VisualizeHistory(self.cfg)
        dfs = {"BTC": viz._read_history("BTC")}
        result = viz.generate_portfolio_chart([], dfs)
        self.assertIsNone(result)

    def test_generate_portfolio_chart_returns_html_with_trades(self):
        hist_dir = self.data_root / "history"
        base_ms = 1_700_000_000_000
        _create_history_csv(hist_dir, "BTC", n=50)
        # Anchor backward reconstruction to current balance
        _create_portfolio_json(self.data_root, {"BTC": 0.01})
        viz = VisualizeHistory(self.cfg)
        dfs = {"BTC": viz._read_history("BTC")}
        trades = [
            {"symbol": "BTCUSDT", "isBuyer": True, "qty": "0.01",
             "price": "40000", "time": base_ms},
        ]
        html_content = viz.generate_portfolio_chart(trades, dfs)
        self.assertIsNotNone(html_content)
        self.assertIn("plotly", html_content.lower())
        self.assertIn("chart-Performance", html_content)

    def test_generate_portfolio_chart_has_rangeselector(self):
        hist_dir = self.data_root / "history"
        base_ms = 1_700_000_000_000
        _create_history_csv(hist_dir, "BTC", n=50)
        # Anchor backward reconstruction to current balance
        _create_portfolio_json(self.data_root, {"BTC": 0.01})
        viz = VisualizeHistory(self.cfg)
        dfs = {"BTC": viz._read_history("BTC")}
        trades = [
            {"symbol": "BTCUSDT", "isBuyer": True, "qty": "0.01",
             "price": "40000", "time": base_ms},
        ]
        html_content = viz.generate_portfolio_chart(trades, dfs)
        self.assertIsNotNone(html_content)
        self.assertIn("rangeselector", html_content.lower())
        self.assertIn('"label":"Senaste veckan"', html_content)
        self.assertIn('"label":"Allt"', html_content)

    # ------------------------------------------------------------------
    # run – portfolio tab integration
    # ------------------------------------------------------------------

    def test_run_includes_portfolio_tab_when_trades_present(self):
        hist_dir = self.data_root / "history"
        base_ms = 1_700_000_000_000
        _create_history_csv(hist_dir, "BTC", n=50)
        trades = [
            {"symbol": "BTCUSDT", "isBuyer": True, "qty": "0.01",
             "price": "40000", "time": base_ms},
        ]
        _create_trades_json(self.data_root / "trades", trades)
        # Anchor backward reconstruction so the portfolio chart is non-empty
        _create_portfolio_json(self.data_root, {"BTC": 0.01})
        viz = VisualizeHistory(self.cfg)
        success = viz.run()
        self.assertTrue(success)
        content = (self.data_root / "visualize" / "history_chart.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="tab-Performance"', content)
        self.assertIn("vh-tab-portfolio", content)
        self.assertIn("chart-Performance", content)

    def test_run_omits_portfolio_tab_when_no_trades(self):
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BTC", n=50)
        viz = VisualizeHistory(self.cfg)
        success = viz.run()
        self.assertTrue(success)
        content = (self.data_root / "visualize" / "history_chart.html").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('id="tab-Performance"', content)

    def test_run_generates_all_charts(self):
        hist_dir = self.data_root / "history"
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
        self.assertNotIn("trade-info", content)

    def test_run_html_contains_created_at_timestamp(self):
        """HTML output should contain a creation timestamp in Europe/Stockholm timezone."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz_sthlm = ZoneInfo("Europe/Stockholm")
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BTC", n=50)
        viz = VisualizeHistory(self.cfg)
        before = datetime.now(tz=tz_sthlm).replace(second=0, microsecond=0)
        success = viz.run()
        after = datetime.now(tz=tz_sthlm).replace(second=0, microsecond=0)
        self.assertTrue(success)
        content = (self.data_root / "visualize" / "history_chart.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("vh-created-at", content)
        # Verify the timestamp follows the expected yyyy-MM-dd HH:mm format
        self.assertRegex(content, r'vh-created-at">\d{4}-\d{2}-\d{2} \d{2}:\d{2}<')
        # Parse the embedded timestamp and verify it falls within the Europe/Stockholm window
        raw = content.split('vh-created-at">')[1].split("<")[0]
        embedded = datetime.strptime(raw, "%Y-%m-%d %H:%M").replace(tzinfo=tz_sthlm)
        self.assertGreaterEqual(embedded, before)
        self.assertLessEqual(embedded, after)

    def test_run_returns_false_when_no_history(self):
        viz = VisualizeHistory(self.cfg)
        success = viz.run()
        self.assertFalse(success)

    def test_combined_html_has_apply_last_month_js(self):
        """Combined HTML must contain applyLastMonth JS called on load and on tab switch."""
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BTC", n=50)
        viz = VisualizeHistory(self.cfg)
        success = viz.run()
        self.assertTrue(success)
        content = (self.data_root / "visualize" / "history_chart.html").read_text(
            encoding="utf-8"
        )
        # Function must be defined
        self.assertIn("function applyLastMonth", content)
        # Active button index 1 = "Senaste månaden" must be set
        self.assertIn("xaxis.rangeselector.active", content)
        # Must be called when switching tabs (inside showChart)
        self.assertIn("applyLastMonth('chart-' + c)", content)
        # Must be called on initial page load for the first chart
        self.assertIn("applyLastMonth('chart-' + _currencies[0])", content)

    # ------------------------------------------------------------------
    # _write_debug_csv
    # ------------------------------------------------------------------

    def _recent_base_ms(self, n: int = 50) -> int:
        """Return a base timestamp so that the last n hourly candles fall within the last week."""
        now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
        return now_ms - n * 3_600_000

    def test_write_debug_csv_creates_file_with_correct_columns(self):
        """_write_debug_csv should create debug.csv with expected columns."""
        base_ms = self._recent_base_ms(50)
        for currency in ["BNB", "ETH"]:
            hist_dir = self.data_root / "history"
            _create_history_csv(hist_dir, currency, n=50, base_ms=base_ms)

        cfg = Config(
            currencies=["BNB", "ETH"],
            binance_secret="s", binance_key="k",
            binance_base_url="https://api.binance.com",
            binance_currency_history_endpoint="/api/v3/klines",
            binance_exchange_info_endpoint="/api/v3/exchangeInfo",
            binance_my_trades_endpoint="/api/v3/myTrades",
            binance_trading_url="https://api.binance.com/api/v3/order",
            dry_run=True, data_area_root_dir=self.test_dir,
            currency_history_period="1h", currency_history_nof_elements=50,
            trade_threshold=10.0, take_profit_percentage=10.0,
            stop_loss_percentage=6.0, allowed_quote_assets=["USDC"],
            ftp_host=None, ftp_dir=None, ftp_username=None,
            ftp_password=None, ftp_html_regexp=None, raw_env={},
        )
        viz = VisualizeHistory(cfg)
        dfs = {
            "BNB": viz._read_history("BNB"),
            "ETH": viz._read_history("ETH"),
        }
        trades = [
            {"symbol": "BNBUSDC", "isBuyer": True, "qty": "1.0",
             "price": "300.0", "quoteQty": "300.0", "time": base_ms},
        ]
        viz._write_debug_csv(trades, dfs)

        debug_file = self.data_root / "visualize" / "debug.csv"
        self.assertTrue(debug_file.exists(), "debug.csv was not created")
        df = pd.read_csv(debug_file)
        for col in ["datetime", "BNB", "ETH", "USDC", "BNBUSDC", "ETHUSDC", "SUM"]:
            self.assertIn(col, df.columns, f"Column '{col}' missing from debug.csv")

    def test_write_debug_csv_sum_equals_components(self):
        """SUM column should equal the sum of all currency USDC value columns plus USDC holdings."""
        base_ms = self._recent_base_ms(10)
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BNB", n=10, base_ms=base_ms)

        cfg = Config(
            currencies=["BNB"],
            binance_secret="s", binance_key="k",
            binance_base_url="https://api.binance.com",
            binance_currency_history_endpoint="/api/v3/klines",
            binance_exchange_info_endpoint="/api/v3/exchangeInfo",
            binance_my_trades_endpoint="/api/v3/myTrades",
            binance_trading_url="https://api.binance.com/api/v3/order",
            dry_run=True, data_area_root_dir=self.test_dir,
            currency_history_period="1h", currency_history_nof_elements=10,
            trade_threshold=10.0, take_profit_percentage=10.0,
            stop_loss_percentage=6.0, allowed_quote_assets=["USDC"],
            ftp_host=None, ftp_dir=None, ftp_username=None,
            ftp_password=None, ftp_html_regexp=None, raw_env={},
        )
        viz = VisualizeHistory(cfg)
        dfs = {"BNB": viz._read_history("BNB")}
        trades = [
            {"symbol": "BNBUSDC", "isBuyer": True, "qty": "2.0",
             "price": "300.0", "quoteQty": "600.0", "time": base_ms},
        ]
        viz._write_debug_csv(trades, dfs)

        debug_file = self.data_root / "visualize" / "debug.csv"
        self.assertTrue(debug_file.exists())
        df = pd.read_csv(debug_file)
        # Dynamically find all <CURRENCY>USDC value columns
        value_cols = [c for c in df.columns if c.endswith("USDC") and c != "USDC"]
        for _, row in df.iterrows():
            expected_sum = row["USDC"] + sum(row[c] for c in value_cols)
            self.assertAlmostEqual(row["SUM"], expected_sum, places=6)

    def test_write_debug_csv_not_created_for_old_data(self):
        """If all history data is older than 7 days, debug.csv should not be written."""
        hist_dir = self.data_root / "history"
        # Use the old default base_ms (2023) which is definitely more than a week ago
        _create_history_csv(hist_dir, "BNB", n=10)

        cfg = Config(
            currencies=["BNB"],
            binance_secret="s", binance_key="k",
            binance_base_url="https://api.binance.com",
            binance_currency_history_endpoint="/api/v3/klines",
            binance_exchange_info_endpoint="/api/v3/exchangeInfo",
            binance_my_trades_endpoint="/api/v3/myTrades",
            binance_trading_url="https://api.binance.com/api/v3/order",
            dry_run=True, data_area_root_dir=self.test_dir,
            currency_history_period="1h", currency_history_nof_elements=10,
            trade_threshold=10.0, take_profit_percentage=10.0,
            stop_loss_percentage=6.0, allowed_quote_assets=["USDC"],
            ftp_host=None, ftp_dir=None, ftp_username=None,
            ftp_password=None, ftp_html_regexp=None, raw_env={},
        )
        viz = VisualizeHistory(cfg)
        dfs = {"BNB": viz._read_history("BNB")}
        viz._write_debug_csv([], dfs)

        debug_file = self.data_root / "visualize" / "debug.csv"
        self.assertFalse(debug_file.exists(), "debug.csv should not be created for old data")

    def test_run_writes_debug_csv_with_recent_data(self):
        """run() should write debug.csv when recent price history is available."""
        base_ms = self._recent_base_ms(50)
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BTC", n=50, base_ms=base_ms)
        viz = VisualizeHistory(self.cfg)
        success = viz.run()
        self.assertTrue(success)
        debug_file = self.data_root / "visualize" / "debug.csv"
        self.assertTrue(debug_file.exists(), "debug.csv should be written by run()")

    def test_write_debug_csv_usdc_anchored_to_portfolio_balance(self):
        """USDC column should be anchored to the current balance from portfolio.json."""
        base_ms = self._recent_base_ms(10)
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BNB", n=10, base_ms=base_ms)

        # Write a portfolio.json with a known USDC balance
        current_usdc = 0.04460852
        portfolio_dir = self.data_root / "portfolio"
        portfolio_dir.mkdir(parents=True, exist_ok=True)
        with open(portfolio_dir / "portfolio.json", "w", encoding="utf-8") as f:
            json.dump({"balances": {"USDC": {"total": str(current_usdc)}}}, f)

        cfg = Config(
            currencies=["BNB"],
            binance_secret="s", binance_key="k",
            binance_base_url="https://api.binance.com",
            binance_currency_history_endpoint="/api/v3/klines",
            binance_exchange_info_endpoint="/api/v3/exchangeInfo",
            binance_my_trades_endpoint="/api/v3/myTrades",
            binance_trading_url="https://api.binance.com/api/v3/order",
            dry_run=True, data_area_root_dir=self.test_dir,
            currency_history_period="1h", currency_history_nof_elements=10,
            trade_threshold=10.0, take_profit_percentage=10.0,
            stop_loss_percentage=6.0, allowed_quote_assets=["USDC"],
            ftp_host=None, ftp_dir=None, ftp_username=None,
            ftp_password=None, ftp_html_regexp=None, raw_env={},
        )
        viz = VisualizeHistory(cfg)
        dfs = {"BNB": viz._read_history("BNB")}
        # Simulate many buy trades that would have made USDC very negative with the old logic
        trades = [
            {"symbol": "BNBUSDC", "isBuyer": True, "qty": "0.5",
             "price": "300.0", "quoteQty": "150.0",
             "time": base_ms + i * 3_600_000}
            for i in range(5)
        ]
        viz._write_debug_csv(trades, dfs)

        debug_file = self.data_root / "visualize" / "debug.csv"
        self.assertTrue(debug_file.exists())
        df = pd.read_csv(debug_file)
        # The last row should show the current USDC balance (net of all flows)
        last_usdc = df["USDC"].iloc[-1]
        self.assertAlmostEqual(last_usdc, current_usdc, places=6,
                               msg="Last USDC value must equal portfolio.json balance")

    def test_write_debug_csv_backward_reconstruction_correct_candle(self):
        """
        Holdings history must be reconstructed by walking backwards from portfolio.json.

        Starting from the current known balance, each trade's net flow is undone to
        recover the balance at each prior candle.  A buy at candle T must appear in
        candle T (not T+1), and the balance in candles before that buy must be lower.
        """
        # Use an hour-aligned base so that floor('h') maps trades to exactly the
        # expected candle index (Binance klines are always on UTC-hour boundaries).
        hour_ms = 3_600_000
        now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
        base_ms = (now_ms // hour_ms - 10) * hour_ms  # aligned to UTC-hour boundary

        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BNB", n=10, base_ms=base_ms)

        # Current BNB balance as known from the exchange.
        # Implied pre-bot balance: 0.309 - 0.159 = 0.150 BNB.
        current_bnb = 0.309
        portfolio_dir = self.data_root / "portfolio"
        portfolio_dir.mkdir(parents=True, exist_ok=True)
        with open(portfolio_dir / "portfolio.json", "w", encoding="utf-8") as f:
            json.dump({"balances": {"BNB": {"total": str(current_bnb)}, "USDC": {"total": "0.0"}}}, f)

        cfg = Config(
            currencies=["BNB"],
            binance_secret="s", binance_key="k",
            binance_base_url="https://api.binance.com",
            binance_currency_history_endpoint="/api/v3/klines",
            binance_exchange_info_endpoint="/api/v3/exchangeInfo",
            binance_my_trades_endpoint="/api/v3/myTrades",
            binance_trading_url="https://api.binance.com/api/v3/order",
            dry_run=True, data_area_root_dir=self.test_dir,
            currency_history_period="1h", currency_history_nof_elements=10,
            trade_threshold=10.0, take_profit_percentage=10.0,
            stop_loss_percentage=6.0, allowed_quote_assets=["USDC"],
            ftp_host=None, ftp_dir=None, ftp_username=None,
            ftp_password=None, ftp_html_regexp=None, raw_env={},
        )
        viz = VisualizeHistory(cfg)
        dfs = {"BNB": viz._read_history("BNB")}

        # One buy 15 minutes into candle index 2 (base_ms + 2h + 15min).
        # floor('h') maps this to exactly base_ms + 2h = candle index 2.
        buy_ms = base_ms + 2 * hour_ms + 15 * 60 * 1000
        trades = [
            {"symbol": "BNBUSDC", "isBuyer": True, "qty": "0.159",
             "price": "622.0", "quoteQty": "98.9", "time": buy_ms},
        ]
        viz._write_debug_csv(trades, dfs)

        debug_file = self.data_root / "visualize" / "debug.csv"
        self.assertTrue(debug_file.exists())
        df = pd.read_csv(debug_file)

        # Last BNB value must match portfolio.json (0.309)
        self.assertAlmostEqual(df["BNB"].iloc[-1], current_bnb, places=6,
                               msg="Last BNB value must equal portfolio.json balance")

        # Candles before the buy (index 0 and 1) must show the pre-buy balance (0.150)
        pre_buy_balance = current_bnb - 0.159
        self.assertAlmostEqual(df["BNB"].iloc[0], pre_buy_balance, places=6,
                               msg="First candle must reflect pre-buy balance")
        self.assertAlmostEqual(df["BNB"].iloc[1], pre_buy_balance, places=6,
                               msg="Candle before the buy must reflect pre-buy balance")

        # The buy candle (index 2) and all later candles must show the post-buy balance
        for row_idx in range(2, len(df)):
            self.assertAlmostEqual(df["BNB"].iloc[row_idx], current_bnb, places=6,
                                   msg=f"Row {row_idx} must reflect post-buy balance")

    # ------------------------------------------------------------------
    # _read_ta_signal
    # ------------------------------------------------------------------

    def _create_ta_csv(self, ta_dir: Path, currency: str, **kwargs) -> None:
        """Create a minimal TA CSV file for testing."""
        ta_dir.mkdir(parents=True, exist_ok=True)
        defaults = {
            "Open_Time_ms": 1_700_003_600_000,
            "Close": 41000.0,
            "RSI_14": 50.0,
            "EMA_12": 41000.0,
            "EMA_21": 40500.0,
            "EMA_26": 40000.0,
            "EMA_50": 39000.0,
            "EMA_200": 38000.0,
            "MACD": 100.0,
            "MACD_Signal": 80.0,
            "MACD_Histogram": 20.0,
        }
        defaults.update(kwargs)
        import csv as _csv
        with open(ta_dir / f"{currency}_ta.csv", "w", newline="", encoding="utf-8") as f:
            writer = _csv.DictWriter(f, fieldnames=list(defaults.keys()))
            writer.writeheader()
            writer.writerow(defaults)

    def test_read_ta_signal_missing_file_returns_dash(self):
        viz = VisualizeHistory(self.cfg)
        result = viz._read_ta_signal("BTC")
        self.assertEqual(result, "–")

    def test_read_ta_signal_returns_buy(self):
        """When all indicators point bullish, signal should be KÖP."""
        ta_dir = self.data_root / "ta"
        self._create_ta_csv(
            ta_dir, "BTC",
            RSI_14=25.0,       # < 30 → +1
            EMA_12=42000.0,    # > EMA_26 → +1
            EMA_26=40000.0,
            MACD=200.0,        # > MACD_Signal → +1
            MACD_Signal=100.0,
            Close=41000.0,     # > EMA_200 → +1
            EMA_200=38000.0,
        )
        viz = VisualizeHistory(self.cfg)
        self.assertEqual(viz._read_ta_signal("BTC"), "KÖP")

    def test_read_ta_signal_returns_sell(self):
        """When all indicators point bearish, signal should be SÄLJ."""
        ta_dir = self.data_root / "ta"
        self._create_ta_csv(
            ta_dir, "BTC",
            RSI_14=75.0,       # > 70 → -1
            EMA_12=38000.0,    # < EMA_26 → -1
            EMA_26=40000.0,
            MACD=-100.0,       # < MACD_Signal → -1
            MACD_Signal=0.0,
            Close=37000.0,     # < EMA_200 → -1
            EMA_200=40000.0,
        )
        viz = VisualizeHistory(self.cfg)
        self.assertEqual(viz._read_ta_signal("BTC"), "SÄLJ")

    def test_read_ta_signal_returns_neutral(self):
        """Mixed signals resulting in score 0 should produce NEUTRAL.

        RSI_14=25 → +1, EMA_12 < EMA_26 → -1, MACD < MACD_Signal → -1, Close > EMA_200 → +1
        Total score = 0 → NEUTRAL.
        """
        ta_dir = self.data_root / "ta"
        self._create_ta_csv(
            ta_dir, "BTC",
            RSI_14=25.0,       # +1
            EMA_12=39000.0,    # < EMA_26 → -1
            EMA_26=40000.0,
            MACD=-50.0,        # < MACD_Signal → -1
            MACD_Signal=0.0,
            Close=41000.0,     # > EMA_200 → +1
            EMA_200=38000.0,
        )
        viz = VisualizeHistory(self.cfg)
        self.assertEqual(viz._read_ta_signal("BTC"), "NEUTRAL")

    # ------------------------------------------------------------------
    # generate_summary_html
    # ------------------------------------------------------------------

    def test_generate_summary_html_returns_div_with_tables(self):
        """generate_summary_html should return a div containing two tables."""
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BTC", n=10)
        _create_portfolio_json(self.data_root, {"BTC": 0.5, "USDC": 100.0})
        viz = VisualizeHistory(self.cfg)
        dfs = {"BTC": viz._read_history("BTC")}
        html = viz.generate_summary_html([], dfs)
        self.assertIn('id="chart-Overview"', html)
        self.assertIn("Portföljöversikt", html)
        self.assertIn("Senaste trades", html)
        self.assertIn("vh-sum-table", html)
        self.assertIn("BTC", html)
        self.assertIn("USDC", html)

    def test_generate_summary_html_shows_holdings(self):
        """Holdings from portfolio.json should appear in the summary table."""
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BTC", n=10)
        _create_portfolio_json(self.data_root, {"BTC": 1.23456, "USDC": 200.0})
        viz = VisualizeHistory(self.cfg)
        dfs = {"BTC": viz._read_history("BTC")}
        html = viz.generate_summary_html([], dfs)
        self.assertIn("1.234560", html)
        self.assertIn("200.000000", html)

    def test_generate_summary_html_shows_ta_signal(self):
        """TA signal read from ta/<currency>_ta.csv should appear in holdings table."""
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BTC", n=10)
        ta_dir = self.data_root / "ta"
        self._create_ta_csv(ta_dir, "BTC",
                            RSI_14=20.0, EMA_12=42000.0, EMA_26=40000.0,
                            MACD=100.0, MACD_Signal=50.0,
                            Close=41000.0, EMA_200=38000.0)
        viz = VisualizeHistory(self.cfg)
        dfs = {"BTC": viz._read_history("BTC")}
        html = viz.generate_summary_html([], dfs)
        self.assertIn("KÖP", html)

    def test_generate_summary_html_shows_latest_trades(self):
        """The ten most recent trades should appear in the summary trades table."""
        base_ms = 1_700_000_000_000
        trades = [
            {"symbol": "BTCUSDT", "isBuyer": True, "qty": "0.01",
             "price": "40000", "quoteQty": "400.0", "time": base_ms},
            {"symbol": "BTCUSDT", "isBuyer": False, "qty": "0.01",
             "price": "42000", "quoteQty": "420.0", "time": base_ms + 3_600_000},
            {"symbol": "BTCUSDT", "isBuyer": True, "qty": "0.02",
             "price": "41000", "quoteQty": "820.0", "time": base_ms + 7_200_000},
            # 11th oldest trade – should NOT appear (only 10 shown)
            {"symbol": "BTCUSDT", "isBuyer": True, "qty": "0.005",
             "price": "39000", "quoteQty": "195.0", "time": base_ms - 3_600_000},
        ]
        # Add 7 more trades so the oldest (195.00 USDC) falls outside the 10 shown
        for i in range(7):
            trades.append({
                "symbol": "BTCUSDT", "isBuyer": False, "qty": "0.01",
                "price": "43000", "quoteQty": f"{500 + i * 10}.0",
                "time": base_ms + (8 + i) * 3_600_000,
            })
        viz = VisualizeHistory(self.cfg)
        html = viz.generate_summary_html(trades, {})
        # The most recent 10 trades should appear
        self.assertIn("420.00 USDC", html)
        self.assertIn("400.00 USDC", html)
        self.assertIn("820.00 USDC", html)
        # The 11th oldest trade's amount should NOT appear
        self.assertNotIn("195.00 USDC", html)

    def test_generate_summary_html_sell_shows_pct_change(self):
        """A SELL trade should display percentage change vs. the preceding BUY."""
        base_ms = 1_700_000_000_000
        trades = [
            {"symbol": "BTCUSDT", "isBuyer": True, "qty": "0.01",
             "price": "40000", "quoteQty": "400.0", "time": base_ms},
            {"symbol": "BTCUSDT", "isBuyer": False, "qty": "0.01",
             "price": "42000", "quoteQty": "420.0", "time": base_ms + 3_600_000},
        ]
        viz = VisualizeHistory(self.cfg)
        html = viz.generate_summary_html(trades, {})
        # sell at 42000 vs buy at 40000 → +5.00%
        self.assertIn("+5.00%", html)

    def test_generate_summary_html_buy_shows_pct_change_vs_latest_price(self):
        """Only the most recent BUY trade should show % change; earlier BUYs show dash."""
        hist_dir = self.data_root / "history"
        # Latest close price = 40000 + 9*10 = 40090 (index -1 of n=10 prices)
        _create_history_csv(hist_dir, "BTC", n=10)
        base_ms = 1_700_000_000_000
        trades = [
            # Older BUY – should NOT show % change
            {"symbol": "BTCUSDT", "isBuyer": True, "qty": "0.01",
             "price": "38000", "quoteQty": "380.0", "time": base_ms},
            # Most recent BUY – SHOULD show % change
            {"symbol": "BTCUSDT", "isBuyer": True, "qty": "0.01",
             "price": "40000", "quoteQty": "400.0", "time": base_ms + 3_600_000},
        ]
        viz = VisualizeHistory(self.cfg)
        dfs = {"BTC": viz._read_history("BTC")}
        html = viz.generate_summary_html(trades, dfs)
        # latest close = 40090, buy price = 40000 → +0.23%
        expected_pct = (40090 - 40000) / 40000 * 100
        sign = "+" if expected_pct >= 0 else ""
        expected_str = f"{sign}{expected_pct:.2f}%"
        self.assertIn(expected_str, html)
        # Older BUY at 38000 should NOT produce a % change value
        older_pct = (40090 - 38000) / 38000 * 100
        older_str = f"+{older_pct:.2f}%"
        self.assertNotIn(older_str, html)

    def test_generate_summary_html_shows_trade_price(self):
        """Trade execution price should appear in the trades table."""
        base_ms = 1_700_000_000_000
        trades = [
            {"symbol": "BTCUSDT", "isBuyer": True, "qty": "0.01",
             "price": "41234.56", "quoteQty": "412.35", "time": base_ms},
        ]
        viz = VisualizeHistory(self.cfg)
        html = viz.generate_summary_html(trades, {})
        self.assertIn("41,234.56", html)

    def test_run_includes_summary_tab(self):
        """run() should always include the Overview tab in the generated HTML."""
        hist_dir = self.data_root / "history"
        _create_history_csv(hist_dir, "BTC", n=50)
        viz = VisualizeHistory(self.cfg)
        success = viz.run()
        self.assertTrue(success)
        content = (self.data_root / "visualize" / "history_chart.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="tab-Overview"', content)
        self.assertIn("vh-tab-summary", content)
        self.assertIn('id="chart-Overview"', content)
        self.assertIn("Portföljöversikt", content)
        self.assertIn("Senaste trades", content)


if __name__ == "__main__":
    unittest.main()

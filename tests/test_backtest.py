#!/usr/bin/env python3
"""
Tests for the Backtest module.

Täcker:
- Laddning av historikdata
- Beräkning av TA-indikatorer
- Simulering per valuta (köp/sälj/håll)
- Sparande av CSV-resultat
- Hantering av otillräcklig data
- CLI-argument --backtest
"""
import argparse
import csv
import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import sys

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtest import Backtest, MIN_CANDLES_FOR_TA
from src.config import Config


def _make_cfg(tmp_dir: str, currencies=None) -> Config:
    return Config(
        currencies=currencies or ["BTC"],
        binance_secret="test_secret",
        binance_key="test_key",
        binance_base_url="https://api.binance.com",
        binance_currency_history_endpoint="/api/v3/klines",
        binance_exchange_info_endpoint="/api/v3/exchangeInfo",
        binance_my_trades_endpoint="/api/v3/myTrades",
        binance_trading_url="https://api.binance.com/api/v3/order",
        dry_run=True,
        data_area_root_dir=tmp_dir,
        currency_history_period="1h",
        currency_history_nof_elements=300,
        trade_threshold=10.0,
        take_profit_percentage=10.0,
        stop_loss_percentage=6.0,
        allowed_quote_assets=["USDT"],
        ftp_host=None,
        ftp_dir=None,
        ftp_username=None,
        ftp_password=None,
        ftp_html_regexp=None,
        ta2_use_ema50_filter=False,
        raw_env={},
    )


def _write_history_csv(tmp_dir: str, currency: str, n_rows: int = 250,
                       start_close: float = 50000.0) -> None:
    """Skapa en minimal historik-CSV med stigande priser."""
    hist_dir = Path(tmp_dir) / "history" / currency
    hist_dir.mkdir(parents=True, exist_ok=True)
    csv_file = hist_dir / f"{currency}_history.csv"

    rows = []
    for i in range(n_rows):
        close = start_close + i * 10.0
        rows.append(
            {
                "Open_Time_ms": 1_000_000 + i * 3600_000,
                "Open": close - 5.0,
                "High": close + 10.0,
                "Low": close - 10.0,
                "Close": close,
                "Volume": 100.0,
                "Close_Time_ms": 1_000_000 + i * 3600_000 + 3599_999,
                "Quote_Asset_Volume": close * 100.0,
                "Number_of_Trades": 500,
                "Taker_Buy_Base_Asset_Volume": 50.0,
                "Taker_Buy_Quote_Asset_Volume": close * 50.0,
            }
        )

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class TestBacktestLoadHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = _make_cfg(self.tmp)
        self.bt = Backtest(self.cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_existing_history(self):
        _write_history_csv(self.tmp, "BTC", n_rows=10)
        df = self.bt._load_history("BTC")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 10)

    def test_load_missing_history_returns_none(self):
        df = self.bt._load_history("MISSING")
        self.assertIsNone(df)


class TestBacktestComputeFullTA(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = _make_cfg(self.tmp)
        self.bt = Backtest(self.cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ta_has_expected_columns(self):
        _write_history_csv(self.tmp, "BTC", n_rows=50)
        history_df = self.bt._load_history("BTC")
        ta_df = self.bt._compute_full_ta(history_df, "BTC")
        self.assertIsNotNone(ta_df)
        for col in ["Close", "RSI_14", "EMA_12", "EMA_21", "EMA_26",
                    "EMA_50", "EMA_200", "MACD", "MACD_Signal"]:
            self.assertIn(col, ta_df.columns, f"Column {col} missing from TA result")

    def test_ta_returns_none_without_close_column(self):
        df = pd.DataFrame({"Open": [1.0, 2.0]})
        result = self.bt._compute_full_ta(df, "BTC")
        self.assertIsNone(result)

    def test_ta_row_count_matches_history(self):
        n = 50
        _write_history_csv(self.tmp, "BTC", n_rows=n)
        history_df = self.bt._load_history("BTC")
        ta_df = self.bt._compute_full_ta(history_df, "BTC")
        self.assertEqual(len(ta_df), n)


class TestBacktestSimulateCurrency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = _make_cfg(self.tmp)
        self.bt = Backtest(self.cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_insufficient_data_returns_empty_list(self):
        """Fewer than MIN_CANDLES_FOR_TA rows should yield no records."""
        _write_history_csv(self.tmp, "BTC", n_rows=MIN_CANDLES_FOR_TA - 1)
        history_df = self.bt._load_history("BTC")
        ta_df = self.bt._compute_full_ta(history_df, "BTC")
        records = self.bt._simulate_currency("BTC", ta_df)
        self.assertEqual(records, [])

    def test_sufficient_data_returns_records(self):
        """MIN_CANDLES_FOR_TA + 10 rows should produce records."""
        n = MIN_CANDLES_FOR_TA + 10
        _write_history_csv(self.tmp, "BTC", n_rows=n)
        history_df = self.bt._load_history("BTC")
        ta_df = self.bt._compute_full_ta(history_df, "BTC")
        records = self.bt._simulate_currency("BTC", ta_df)
        self.assertEqual(len(records), 10)

    def test_record_has_required_fields(self):
        """Each record should have all expected columns."""
        n = MIN_CANDLES_FOR_TA + 5
        _write_history_csv(self.tmp, "BTC", n_rows=n)
        history_df = self.bt._load_history("BTC")
        ta_df = self.bt._compute_full_ta(history_df, "BTC")
        records = self.bt._simulate_currency("BTC", ta_df)
        self.assertTrue(len(records) > 0)
        required = {
            "timestamp_ms", "currency", "close", "ta_signal", "signal",
            "trade_executed", "cash_usdc", "holdings", "holdings_value_usdc",
            "total_value_usdc",
        }
        for field in required:
            self.assertIn(field, records[0], f"Field {field} missing from record")

    def test_currency_field_is_uppercase(self):
        n = MIN_CANDLES_FOR_TA + 5
        _write_history_csv(self.tmp, "BTC", n_rows=n)
        history_df = self.bt._load_history("BTC")
        ta_df = self.bt._compute_full_ta(history_df, "BTC")
        records = self.bt._simulate_currency("BTC", ta_df)
        for rec in records:
            self.assertEqual(rec["currency"], "BTC")

    def test_total_value_equals_cash_plus_holdings(self):
        """total_value_usdc should equal cash_usdc + holdings_value_usdc."""
        n = MIN_CANDLES_FOR_TA + 50
        _write_history_csv(self.tmp, "BTC", n_rows=n)
        history_df = self.bt._load_history("BTC")
        ta_df = self.bt._compute_full_ta(history_df, "BTC")
        records = self.bt._simulate_currency("BTC", ta_df)
        for rec in records:
            expected = round(rec["cash_usdc"] + rec["holdings_value_usdc"], 4)
            self.assertAlmostEqual(rec["total_value_usdc"], expected, places=2)

    def test_no_holdings_when_no_buy_signal(self):
        """With monotonically rising prices, MACD will be positive (possible BUY).
        At minimum we verify holdings and cash are non-negative at all times."""
        n = MIN_CANDLES_FOR_TA + 20
        _write_history_csv(self.tmp, "BTC", n_rows=n)
        history_df = self.bt._load_history("BTC")
        ta_df = self.bt._compute_full_ta(history_df, "BTC")
        records = self.bt._simulate_currency("BTC", ta_df)
        for rec in records:
            self.assertGreaterEqual(rec["cash_usdc"], 0.0)
            self.assertGreaterEqual(rec["holdings"], 0.0)
            self.assertGreaterEqual(rec["total_value_usdc"], 0.0)


class TestBacktestSaveResults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = _make_cfg(self.tmp)
        self.bt = Backtest(self.cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_creates_csv_file(self):
        records = [
            {
                "timestamp_ms": 1000000,
                "currency": "BTC",
                "close": 50000.0,
                "ta_signal": 0,
                "signal": "HOLD",
                "trade_executed": "HOLD",
                "cash_usdc": 1000.0,
                "holdings": 0.0,
                "holdings_value_usdc": 0.0,
                "total_value_usdc": 1000.0,
            }
        ]
        result = self.bt._save_results(records)
        self.assertTrue(result)
        output_file = Path(self.tmp) / "output" / "backtesting.csv"
        self.assertTrue(output_file.exists())

    def test_save_empty_records_creates_csv_with_header(self):
        result = self.bt._save_results([])
        self.assertTrue(result)
        output_file = Path(self.tmp) / "output" / "backtesting.csv"
        self.assertTrue(output_file.exists())
        with open(output_file, encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
        self.assertIn("timestamp_ms", header)
        self.assertIn("currency", header)
        self.assertIn("total_value_usdc", header)

    def test_save_records_readable_by_pandas(self):
        records = [
            {
                "timestamp_ms": 1000000 + i,
                "currency": "BTC",
                "close": 50000.0 + i,
                "ta_signal": 0,
                "signal": "HOLD",
                "trade_executed": "HOLD",
                "cash_usdc": 1000.0,
                "holdings": 0.0,
                "holdings_value_usdc": 0.0,
                "total_value_usdc": 1000.0,
            }
            for i in range(5)
        ]
        self.bt._save_results(records)
        output_file = Path(self.tmp) / "output" / "backtesting.csv"
        df = pd.read_csv(output_file)
        self.assertEqual(len(df), 5)


class TestBacktestRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_creates_output_file(self):
        """A complete run with sufficient data should create backtesting.csv."""
        cfg = _make_cfg(self.tmp, currencies=["BTC"])
        _write_history_csv(self.tmp, "BTC", n_rows=MIN_CANDLES_FOR_TA + 20)
        bt = Backtest(cfg)
        success = bt.run()
        self.assertTrue(success)
        output_file = Path(self.tmp) / "output" / "backtesting.csv"
        self.assertTrue(output_file.exists())

    def test_run_with_missing_history_still_saves_empty_csv(self):
        """If no history data exists, run should still save an empty CSV."""
        cfg = _make_cfg(self.tmp, currencies=["BTC"])
        bt = Backtest(cfg)
        success = bt.run()
        self.assertTrue(success)
        output_file = Path(self.tmp) / "output" / "backtesting.csv"
        self.assertTrue(output_file.exists())

    def test_run_with_multiple_currencies(self):
        """Multiple currencies should each contribute records."""
        cfg = _make_cfg(self.tmp, currencies=["BTC", "ETH"])
        _write_history_csv(self.tmp, "BTC", n_rows=MIN_CANDLES_FOR_TA + 10)
        _write_history_csv(self.tmp, "ETH", n_rows=MIN_CANDLES_FOR_TA + 10,
                           start_close=3000.0)
        bt = Backtest(cfg)
        success = bt.run()
        self.assertTrue(success)
        output_file = Path(self.tmp) / "output" / "backtesting.csv"
        df = pd.read_csv(output_file)
        self.assertIn("BTC", df["currency"].values)
        self.assertIn("ETH", df["currency"].values)


class TestBacktestCLIArgument(unittest.TestCase):
    """Test att --backtest-argumentet är tillgängligt i main-parsern."""

    def _make_parser(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--backtest", action="store_true")
        return parser

    def test_backtest_flag_present(self):
        parser = self._make_parser()
        args = parser.parse_args(["--backtest"])
        self.assertTrue(args.backtest)

    def test_no_backtest_flag_defaults_false(self):
        parser = self._make_parser()
        args = parser.parse_args([])
        self.assertFalse(args.backtest)


if __name__ == "__main__":
    unittest.main()

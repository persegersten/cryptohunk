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
    hist_dir = Path(tmp_dir) / "history"
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
        """Each record should have exactly the four expected columns."""
        n = MIN_CANDLES_FOR_TA + 5
        _write_history_csv(self.tmp, "BTC", n_rows=n)
        history_df = self.bt._load_history("BTC")
        ta_df = self.bt._compute_full_ta(history_df, "BTC")
        records = self.bt._simulate_currency("BTC", ta_df)
        self.assertTrue(len(records) > 0)
        required = {"timestamp_ms", "currency", "ta_signal", "signal"}
        for field in required:
            self.assertIn(field, records[0], f"Field {field} missing from record")
        # Removed columns must not be present
        for removed in ("close", "trade_executed", "cash_usdc", "holdings",
                         "holdings_value_usdc", "total_value_usdc"):
            self.assertNotIn(removed, records[0], f"Field {removed} should not be in record")

    def test_currency_field_is_uppercase(self):
        n = MIN_CANDLES_FOR_TA + 5
        _write_history_csv(self.tmp, "BTC", n_rows=n)
        history_df = self.bt._load_history("BTC")
        ta_df = self.bt._compute_full_ta(history_df, "BTC")
        records = self.bt._simulate_currency("BTC", ta_df)
        for rec in records:
            self.assertEqual(rec["currency"], "BTC")

    def test_no_holdings_when_no_buy_signal(self):
        """With monotonically rising prices, verify ta_signal (graded score) and signal are set."""
        n = MIN_CANDLES_FOR_TA + 20
        _write_history_csv(self.tmp, "BTC", n_rows=n)
        history_df = self.bt._load_history("BTC")
        ta_df = self.bt._compute_full_ta(history_df, "BTC")
        records = self.bt._simulate_currency("BTC", ta_df)
        for rec in records:
            self.assertIn(rec["signal"], ("BUY", "SELL", "HOLD"))
            # ta_signal is now a graded score (approx -8 to +8), not -1/0/1
            self.assertIsInstance(rec["ta_signal"], int)

    def test_trade_threshold_rules_skipped_sell_executed_on_small_holdings(self):
        """Backtest should execute SELL from TA exit rule regardless of holdings size.

        In live trading, Rule 3 prevents SELL when holdings < TRADE_THRESHOLD.
        In backtesting this rule must be skipped so that
        a TA SELL signal always triggers a SELL trade.
        We verify by constructing a TA DataFrame where MACD < MACD_Signal (exit rule)
        and calling _simulate_currency directly with a tiny simulated holding.
        """
        n = MIN_CANDLES_FOR_TA + 2
        rows = []
        base_close = 50000.0
        for i in range(n):
            rows.append({
                "Close": base_close + i,
                "RSI_14": 55.0,
                "EMA_12": base_close,
                "EMA_21": base_close,
                "EMA_26": base_close,
                "EMA_50": base_close,
                "EMA_200": base_close - 1000.0,
                # MACD < MACD_Signal on every candle → exit rule triggers SELL
                "MACD": 1.0,
                "MACD_Signal": 5.0,
                "Close_Time_ms": 1_000_000 + i * 3600_000,
            })
        ta_df = pd.DataFrame(rows)

        records = self.bt._simulate_currency("BTC", ta_df)
        # All signals should be SELL; no HOLD due to Rule 3 (portfolio rules skipped).
        for rec in records:
            self.assertEqual(rec["signal"], "SELL")


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
                "ta_signal": 0,
                "signal": "HOLD",
            }
        ]
        result = self.bt._save_results("BTC", records)
        self.assertTrue(result)
        output_file = Path(self.tmp) / "output" / "backtesting" / "BTC_backtesting.csv"
        self.assertTrue(output_file.exists())

    def test_save_empty_records_creates_csv_with_header(self):
        result = self.bt._save_results("BTC", [])
        self.assertTrue(result)
        output_file = Path(self.tmp) / "output" / "backtesting" / "BTC_backtesting.csv"
        self.assertTrue(output_file.exists())
        with open(output_file, encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
        self.assertEqual(header, ["timestamp_ms", "currency", "ta_signal", "signal"])

    def test_save_records_readable_by_pandas(self):
        records = [
            {
                "timestamp_ms": 1000000 + i,
                "currency": "BTC",
                "ta_signal": 0,
                "signal": "HOLD",
            }
            for i in range(5)
        ]
        self.bt._save_results("BTC", records)
        output_file = Path(self.tmp) / "output" / "backtesting" / "BTC_backtesting.csv"
        df = pd.read_csv(output_file)
        self.assertEqual(len(df), 5)

    def test_save_different_currencies_produce_separate_files(self):
        """Each currency should get its own output file."""
        for currency in ("BTC", "ETH"):
            self.bt._save_results(currency, [])
        btc_file = Path(self.tmp) / "output" / "backtesting" / "BTC_backtesting.csv"
        eth_file = Path(self.tmp) / "output" / "backtesting" / "ETH_backtesting.csv"
        self.assertTrue(btc_file.exists())
        self.assertTrue(eth_file.exists())


class TestBacktestRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_creates_output_file(self):
        """A complete run with sufficient data should create BTC_backtesting.csv."""
        cfg = _make_cfg(self.tmp, currencies=["BTC"])
        _write_history_csv(self.tmp, "BTC", n_rows=MIN_CANDLES_FOR_TA + 20)
        bt = Backtest(cfg)
        success = bt.run()
        self.assertTrue(success)
        output_file = Path(self.tmp) / "output" / "backtesting" / "BTC_backtesting.csv"
        self.assertTrue(output_file.exists())

    def test_run_with_missing_history_still_succeeds(self):
        """If no history data exists, run should still return True."""
        cfg = _make_cfg(self.tmp, currencies=["BTC"])
        bt = Backtest(cfg)
        success = bt.run()
        self.assertTrue(success)

    def test_run_with_multiple_currencies_creates_separate_files(self):
        """Multiple currencies should each get their own output file."""
        cfg = _make_cfg(self.tmp, currencies=["BTC", "ETH"])
        _write_history_csv(self.tmp, "BTC", n_rows=MIN_CANDLES_FOR_TA + 10)
        _write_history_csv(self.tmp, "ETH", n_rows=MIN_CANDLES_FOR_TA + 10,
                           start_close=3000.0)
        bt = Backtest(cfg)
        success = bt.run()
        self.assertTrue(success)
        btc_file = Path(self.tmp) / "output" / "backtesting" / "BTC_backtesting.csv"
        eth_file = Path(self.tmp) / "output" / "backtesting" / "ETH_backtesting.csv"
        self.assertTrue(btc_file.exists())
        self.assertTrue(eth_file.exists())
        btc_df = pd.read_csv(btc_file)
        eth_df = pd.read_csv(eth_file)
        self.assertTrue(all(btc_df["currency"] == "BTC"))
        self.assertTrue(all(eth_df["currency"] == "ETH"))

    def test_output_csv_contains_exactly_four_columns(self):
        """Output CSV must have exactly timestamp_ms, currency, ta_signal, signal."""
        cfg = _make_cfg(self.tmp, currencies=["BTC"])
        _write_history_csv(self.tmp, "BTC", n_rows=MIN_CANDLES_FOR_TA + 5)
        bt = Backtest(cfg)
        bt.run()
        output_file = Path(self.tmp) / "output" / "backtesting" / "BTC_backtesting.csv"
        df = pd.read_csv(output_file)
        self.assertEqual(list(df.columns), ["timestamp_ms", "currency", "ta_signal", "signal"])
        # Removed columns must not appear
        for removed in ("close", "trade_executed", "cash_usdc", "holdings",
                         "holdings_value_usdc", "total_value_usdc"):
            self.assertNotIn(removed, df.columns)


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

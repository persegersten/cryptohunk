#!/usr/bin/env python3
"""
Tests for TA2 strategy (long-only trend-following pullback).

Covers:
- --run-ta and --run-ta2 mutual exclusivity
- TA2 entry detection including RSI cross and reset window excluding entry candle
- Optional EMA50 filter behaviour
- TA2 exit (MACD cross down) behaviour
- That take profit / stop loss overrides still apply when TA2 would otherwise HOLD/BUY/SELL
"""
import argparse
import unittest
import tempfile
import shutil
from pathlib import Path
import pandas as pd
import sys

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.rebalance_portfolio import RebalancePortfolio
from src.config import Config


def _make_cfg(tmp_dir, ta2_use_ema50_filter=False):
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
        data_area_root_dir=str(tmp_dir),
        currency_history_period="1h",
        currency_history_nof_elements=300,
        trade_threshold=100.0,
        take_profit_percentage=10.0,
        stop_loss_percentage=6.0,
        allowed_quote_assets=["USDT"],
        ta2_use_ema50_filter=ta2_use_ema50_filter,
        raw_env={},
    )


def _build_ta_df(
    n_rows=20,
    close=55000.0,
    ema_200=50000.0,
    ema_21=54000.0,
    ema_50=52000.0,
    macd=10.0,
    macd_signal=5.0,
    # RSI series: control t-1 and t, and the lookback window
    rsi_lookback_min=40.0,   # min RSI in t-8..t-1 (should be < 45 for entry)
    rsi_t_minus_1=48.0,      # RSI at t-1 (should be <= 50 for cross)
    rsi_t=52.0,              # RSI at t (should be > 50 for cross)
):
    """Build a minimal DataFrame that satisfies (or can be tweaked to fail) TA2 entry/exit rules."""
    rows = n_rows
    # Build RSI series: fill lookback window with rsi_lookback_min, then t-1, then t
    rsi_values = [55.0] * rows  # default neutral
    # Set the 8 candles before t-1 (indices rows-10 to rows-2) to rsi_lookback_min
    for i in range(rows - 9, rows - 1):  # t-8 to t-1 are indices rows-9 to rows-2 (0-based)
        rsi_values[i] = rsi_lookback_min
    rsi_values[-2] = rsi_t_minus_1  # t-1
    rsi_values[-1] = rsi_t          # t

    data = {
        "Close": [close] * rows,
        "EMA_200": [ema_200] * rows,
        "EMA_21": [ema_21] * rows,
        "EMA_50": [ema_50] * rows,
        "MACD": [macd] * rows,
        "MACD_Signal": [macd_signal] * rows,
        "RSI_14": rsi_values,
    }
    return pd.DataFrame(data)


class TestMutualExclusivity(unittest.TestCase):
    """Test that --run-ta and --run-ta2 are mutually exclusive in argparse."""

    def _make_parser(self):
        parser = argparse.ArgumentParser()
        ta_group = parser.add_mutually_exclusive_group()
        ta_group.add_argument("--run-ta", action="store_true")
        ta_group.add_argument("--run-ta2", action="store_true")
        return parser

    def test_run_ta_alone(self):
        parser = self._make_parser()
        args = parser.parse_args(["--run-ta"])
        self.assertTrue(args.run_ta)
        self.assertFalse(args.run_ta2)

    def test_run_ta2_alone(self):
        parser = self._make_parser()
        args = parser.parse_args(["--run-ta2"])
        self.assertFalse(args.run_ta)
        self.assertTrue(args.run_ta2)

    def test_both_flags_raises(self):
        parser = self._make_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--run-ta", "--run-ta2"])

    def test_neither_flag_ok(self):
        parser = self._make_parser()
        args = parser.parse_args([])
        self.assertFalse(args.run_ta)
        self.assertFalse(args.run_ta2)


class TestTA2SignalEntry(unittest.TestCase):
    """Test TA2 entry (BUY) signal detection."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = _make_cfg(self.tmp)
        self.rebalancer = RebalancePortfolio(self.cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_buy_signal_when_all_conditions_met(self):
        df = _build_ta_df()
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertEqual(result, 1)  # BUY

    def test_no_buy_when_close_below_ema_200(self):
        df = _build_ta_df(close=49000.0, ema_200=50000.0)
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertNotEqual(result, 1)

    def test_no_buy_when_close_below_ema_21(self):
        df = _build_ta_df(close=55000.0, ema_21=56000.0)
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertNotEqual(result, 1)

    def test_no_buy_when_macd_below_signal(self):
        # MACD < MACD_Signal → SELL
        df = _build_ta_df(macd=3.0, macd_signal=5.0)
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertEqual(result, -1)  # SELL, not BUY

    def test_no_buy_when_rsi_does_not_cross(self):
        # RSI was already above 50 at t-1 (no cross)
        df = _build_ta_df(rsi_t_minus_1=55.0, rsi_t=60.0)
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertNotEqual(result, 1)

    def test_no_buy_when_rsi_t_not_above_50(self):
        # RSI(t) does not cross above 50
        df = _build_ta_df(rsi_t_minus_1=48.0, rsi_t=49.0)
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertNotEqual(result, 1)

    def test_no_buy_when_lookback_reset_missing(self):
        # Lookback min RSI >= 45 → no pullback reset
        df = _build_ta_df(rsi_lookback_min=50.0)
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertNotEqual(result, 1)

    def test_lookback_excludes_entry_candle(self):
        """RSI at t is high but lookback window (t-8..t-1) still has a low value."""
        df = _build_ta_df(
            rsi_lookback_min=40.0,  # < 45, inside t-8..t-1
            rsi_t_minus_1=48.0,
            rsi_t=55.0,
        )
        # Override entry candle RSI to be high (should not affect lookback)
        df.loc[df.index[-1], "RSI_14"] = 55.0
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertEqual(result, 1)  # BUY — entry candle not in lookback

    def test_not_enough_rows_returns_hold(self):
        df = _build_ta_df(n_rows=5)  # < 9 rows needed
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertEqual(result, 0)  # HOLD

    def test_hold_when_macd_equals_signal(self):
        # MACD == MACD_Signal → neither BUY nor SELL
        df = _build_ta_df(macd=5.0, macd_signal=5.0)
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertEqual(result, 0)  # HOLD


class TestTA2SignalExit(unittest.TestCase):
    """Test TA2 exit (SELL) signal detection."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = _make_cfg(self.tmp)
        self.rebalancer = RebalancePortfolio(self.cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sell_when_macd_below_signal(self):
        df = _build_ta_df(macd=3.0, macd_signal=5.0)
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertEqual(result, -1)  # SELL

    def test_sell_regardless_of_other_conditions(self):
        # Even if all entry conditions are met, MACD < MACD_Signal should trigger SELL
        df = _build_ta_df(
            macd=1.0,
            macd_signal=5.0,
            rsi_t_minus_1=48.0,
            rsi_t=52.0,
            rsi_lookback_min=40.0,
        )
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertEqual(result, -1)


class TestTA2EMA50Filter(unittest.TestCase):
    """Test optional EMA50 trend-strength filter for TA2."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ema50_filter_disabled_by_default(self):
        """When filter off, EMA50 <= EMA200 should not block BUY."""
        cfg = _make_cfg(self.tmp, ta2_use_ema50_filter=False)
        rebalancer = RebalancePortfolio(cfg)
        # EMA_50 < EMA_200 but filter disabled
        df = _build_ta_df(ema_50=48000.0, ema_200=50000.0)
        result = rebalancer._calculate_ta2_signal(df)
        self.assertEqual(result, 1)  # BUY, filter not applied

    def test_ema50_filter_blocks_buy_when_ema50_below_ema200(self):
        """When filter on, EMA50 <= EMA200 should block BUY → HOLD."""
        cfg = _make_cfg(self.tmp, ta2_use_ema50_filter=True)
        rebalancer = RebalancePortfolio(cfg)
        df = _build_ta_df(ema_50=48000.0, ema_200=50000.0)
        result = rebalancer._calculate_ta2_signal(df)
        self.assertEqual(result, 0)  # HOLD

    def test_ema50_filter_allows_buy_when_ema50_above_ema200(self):
        """When filter on and EMA50 > EMA200, BUY is allowed."""
        cfg = _make_cfg(self.tmp, ta2_use_ema50_filter=True)
        rebalancer = RebalancePortfolio(cfg)
        df = _build_ta_df(ema_50=52000.0, ema_200=50000.0)
        result = rebalancer._calculate_ta2_signal(df)
        self.assertEqual(result, 1)  # BUY


class TestTA2OverrideRules(unittest.TestCase):
    """Test that take profit / stop loss overrides apply even when TA2 says HOLD/BUY/SELL."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = _make_cfg(self.tmp)
        self.rebalancer = RebalancePortfolio(self.cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_take_profit_overrides_ta2_hold(self):
        """Rule 1: holdings < threshold AND profit > take_profit_pct → SELL even if TA2 says HOLD."""
        signal, priority = self.rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,  # TA2 HOLD
            current_value_usdc=50.0,   # < 100 threshold
            percentage_change=15.0,    # > 10% profit
        )
        self.assertEqual(signal, "SELL")
        self.assertEqual(priority, 1)

    def test_stop_loss_overrides_ta2_buy(self):
        """Rule 2: holdings >= threshold AND loss > stop_loss_pct → SELL even if TA2 says BUY."""
        signal, priority = self.rebalancer._generate_signal(
            currency="BTC",
            ta_score=1,   # TA2 BUY
            current_value_usdc=500.0,  # >= 100 threshold
            percentage_change=-7.0,    # > 6% loss
        )
        self.assertEqual(signal, "SELL")
        self.assertEqual(priority, 2)

    def test_rule3_prevents_sell_on_small_holdings(self):
        """Rule 3: holdings < threshold → HOLD instead of SELL (even if TA2 says SELL)."""
        signal, priority = self.rebalancer._generate_signal(
            currency="BTC",
            ta_score=-1,  # TA2 SELL
            current_value_usdc=50.0,   # < 100 threshold
            percentage_change=5.0,     # < 10% profit
        )
        self.assertEqual(signal, "HOLD")
        self.assertEqual(priority, 3)

    def test_ta2_sell_allowed_above_threshold(self):
        """TA2 SELL is allowed when holdings >= threshold (no overriding rule)."""
        signal, priority = self.rebalancer._generate_signal(
            currency="BTC",
            ta_score=-1,  # TA2 SELL
            current_value_usdc=500.0,  # >= 100 threshold
            percentage_change=5.0,
        )
        self.assertEqual(signal, "SELL")
        self.assertEqual(priority, 3)

    def test_ta2_buy_passes_through(self):
        """TA2 BUY passes through when no override rule applies."""
        signal, priority = self.rebalancer._generate_signal(
            currency="BTC",
            ta_score=1,   # TA2 BUY
            current_value_usdc=500.0,
            percentage_change=5.0,
        )
        self.assertEqual(signal, "BUY")
        self.assertEqual(priority, 3)


if __name__ == "__main__":
    unittest.main()

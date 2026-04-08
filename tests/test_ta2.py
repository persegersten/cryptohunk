#!/usr/bin/env python3
"""
Tests for TA2 strategy (long-only MACD-cross trend-following).

Covers:
- TA2 entry detection including bullish MACD cross and trend filter
- Optional EMA50 filter behaviour
- TA2 exit (MACD bearish or Close < EMA_21) behaviour
- That take profit / stop loss overrides still apply when TA2 would otherwise HOLD/BUY/SELL
"""
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
        take_profit_percentage=3.0,
        stop_loss_percentage=3.0,
        allowed_quote_assets=["USDT"],
        ftp_host=None,
        ftp_dir=None,
        ftp_username=None,
        ftp_password=None,
        ftp_html_regexp=None,
        raw_env={},
        ta2_use_ema50_filter=ta2_use_ema50_filter,
    )


def _build_ta_df(
    n_rows=20,
    close=55000.0,
    ema_200=50000.0,
    ema_21=54000.0,
    ema_50=52000.0,
    macd=10.0,
    macd_signal=5.0,
    # MACD cross: control t-1 values for bullish cross detection
    macd_prev=4.0,           # MACD at t-1 (should be <= macd_signal_prev for cross)
    macd_signal_prev=5.0,    # MACD_Signal at t-1
):
    """Build a minimal DataFrame that satisfies (or can be tweaked to fail) TA2 entry/exit rules."""
    rows = n_rows

    data = {
        "Close": [close] * rows,
        "EMA_200": [ema_200] * rows,
        "EMA_21": [ema_21] * rows,
        "EMA_50": [ema_50] * rows,
        "MACD": [macd] * rows,
        "MACD_Signal": [macd_signal] * rows,
    }
    df = pd.DataFrame(data)
    # Set previous candle MACD values for cross detection
    df.loc[df.index[-2], "MACD"] = macd_prev
    df.loc[df.index[-2], "MACD_Signal"] = macd_signal_prev
    return df


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

    def test_no_buy_when_no_macd_cross(self):
        # MACD was already above signal at t-1 (no cross)
        df = _build_ta_df(macd_prev=10.0, macd_signal_prev=5.0)
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertNotEqual(result, 1)

    def test_no_buy_when_macd_prev_above_signal_prev(self):
        # MACD(t-1) > MACD_Signal(t-1) → no bullish cross
        df = _build_ta_df(macd=10.0, macd_signal=5.0, macd_prev=6.0, macd_signal_prev=5.0)
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertNotEqual(result, 1)

    def test_buy_when_macd_prev_equals_signal_prev(self):
        # MACD(t-1) == MACD_Signal(t-1) is valid for cross (<=)
        df = _build_ta_df(macd=10.0, macd_signal=5.0, macd_prev=5.0, macd_signal_prev=5.0)
        result = self.rebalancer._calculate_ta2_signal(df)
        self.assertEqual(result, 1)  # BUY

    def test_minimal_rows_returns_valid_signal(self):
        df = _build_ta_df(n_rows=2)
        # Only 2 rows - minimal, but should work (we need at least 2)
        result = self.rebalancer._calculate_ta2_signal(df)
        # With 2 rows it should be able to compute (prev + last)
        self.assertIn(result, [0, 1, -1])

    def test_single_row_returns_hold(self):
        data = {
            "Close": [55000.0],
            "EMA_200": [50000.0],
            "EMA_21": [54000.0],
            "EMA_50": [52000.0],
            "MACD": [10.0],
            "MACD_Signal": [5.0],
        }
        df = pd.DataFrame(data)
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
            percentage_change=5.0,     # > 3% profit
            macd_sell=False,
        )
        self.assertEqual(signal, "SELL")
        self.assertEqual(priority, 1)

    def test_stop_loss_overrides_ta2_buy(self):
        """Rule 2: holdings >= threshold AND loss > stop_loss_pct → SELL even if TA2 says BUY."""
        signal, priority = self.rebalancer._generate_signal(
            currency="BTC",
            ta_score=6,   # TA2 BUY (score >= threshold)
            current_value_usdc=500.0,  # >= 100 threshold
            percentage_change=-4.0,    # > 3% loss
            macd_sell=False,
        )
        self.assertEqual(signal, "SELL")
        self.assertEqual(priority, 2)

    def test_rule3_prevents_sell_on_small_holdings(self):
        """Rule 3: holdings < threshold → HOLD instead of SELL (even if MACD says SELL)."""
        signal, priority = self.rebalancer._generate_signal(
            currency="BTC",
            ta_score=-4,  # Bearish TA
            current_value_usdc=50.0,   # < 100 threshold
            percentage_change=2.0,     # < 3% profit
            macd_sell=True,  # MACD exit rule triggered
        )
        self.assertEqual(signal, "HOLD")
        self.assertEqual(priority, 3)

    def test_ta2_sell_allowed_above_threshold(self):
        """TA2 SELL is allowed when holdings >= threshold (no overriding rule)."""
        signal, priority = self.rebalancer._generate_signal(
            currency="BTC",
            ta_score=-4,  # Bearish TA
            current_value_usdc=500.0,  # >= 100 threshold
            percentage_change=2.0,     # < 3% take_profit, so TA signal applies
            macd_sell=True,  # MACD exit rule triggered
        )
        self.assertEqual(signal, "SELL")
        self.assertEqual(priority, 3)

    def test_ta2_buy_passes_through(self):
        """TA2 BUY passes through when no override rule applies."""
        signal, priority = self.rebalancer._generate_signal(
            currency="BTC",
            ta_score=6,   # TA2 BUY (score >= threshold)
            current_value_usdc=500.0,
            percentage_change=2.0,     # < 3% take_profit, so TA signal applies
            macd_sell=False,
        )
        self.assertEqual(signal, "BUY")
        self.assertEqual(priority, 3)

    def test_take_profit_triggers_above_threshold(self):
        """Rule 1: profit > take_profit_pct → SELL even when holdings >= threshold."""
        signal, priority = self.rebalancer._generate_signal(
            currency="BTC",
            ta_score=6,   # TA2 BUY (would normally buy)
            current_value_usdc=500.0,  # >= 100 threshold
            percentage_change=5.0,     # > 3% take_profit
            macd_sell=False,
        )
        self.assertEqual(signal, "SELL")
        self.assertEqual(priority, 1)


if __name__ == "__main__":
    unittest.main()

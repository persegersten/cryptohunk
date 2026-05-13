#!/usr/bin/env python3
import csv
import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import sys

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtest import MIN_CANDLES_FOR_TA
from src.config import Config
from src.optimize_risk_parameters import OptimizeRiskParameters


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
        allowed_quote_assets=["USDC"],
        ftp_host=None,
        ftp_dir=None,
        ftp_username=None,
        ftp_password=None,
        ftp_html_regexp=None,
        ta2_use_ema50_filter=False,
        raw_env={},
    )


def _make_ta_df(closes):
    rows = []
    for i, close in enumerate(closes):
        rows.append(
            {
                "Close": float(close),
                "RSI_14": 55.0,
                "EMA_12": float(close),
                "EMA_21": float(close) - 1.0,
                "EMA_26": float(close),
                "EMA_50": float(close) - 2.0,
                "EMA_200": float(close) - 10.0,
                "MACD": 2.0,
                "MACD_Signal": 1.0,
                "Close_Time_ms": 1_000_000 + i * 3600_000,
            }
        )
    return pd.DataFrame(rows)


def _write_history_csv(tmp_dir: str, currency: str, closes) -> None:
    hist_dir = Path(tmp_dir) / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    csv_file = hist_dir / f"{currency}_history.csv"

    rows = []
    for i, close in enumerate(closes):
        rows.append(
            {
                "Open_Time_ms": 1_000_000 + i * 3600_000,
                "Open": close,
                "High": close,
                "Low": close,
                "Close": close,
                "Volume": 100.0,
                "Close_Time_ms": 1_000_000 + i * 3600_000 + 3599_999,
            }
        )

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class TestOptimizeRiskParameters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.optimizer = OptimizeRiskParameters(_make_cfg(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_take_profit_exit_improves_return(self):
        closes = [100.0] * MIN_CANDLES_FOR_TA + [100.0, 101.0, 103.0, 106.0, 110.0]
        ta_df = _make_ta_df(closes)
        self.optimizer._ta_signal = lambda window: "BUY" if len(window) == MIN_CANDLES_FOR_TA + 1 else "HOLD"

        row = self.optimizer._simulate_parameters("BTC", ta_df, 5.0, 10.0)

        self.assertEqual(row["trades"], 1)
        self.assertEqual(row["total_return_pct"], "6.00")
        self.assertEqual(row["win_rate_pct"], "100.00")

    def test_stop_loss_exit_limits_loss(self):
        closes = [100.0] * MIN_CANDLES_FOR_TA + [100.0, 98.0, 94.0, 90.0]
        ta_df = _make_ta_df(closes)
        self.optimizer._ta_signal = lambda window: "BUY" if len(window) == MIN_CANDLES_FOR_TA + 1 else "HOLD"

        row = self.optimizer._simulate_parameters("BTC", ta_df, 10.0, 5.0)

        self.assertEqual(row["trades"], 1)
        self.assertEqual(row["total_return_pct"], "-6.00")
        self.assertEqual(row["win_rate_pct"], "0.00")

    def test_ta_sell_exits_when_take_profit_and_stop_loss_do_not_trigger(self):
        closes = [100.0] * MIN_CANDLES_FOR_TA + [100.0, 102.0, 104.0, 106.0]
        ta_df = _make_ta_df(closes)
        signals = ["HOLD"] * len(ta_df)
        signals[MIN_CANDLES_FOR_TA] = "BUY"
        signals[MIN_CANDLES_FOR_TA + 2] = "SELL"

        row = self.optimizer._simulate_parameters(
            "BTC",
            ta_df,
            take_profit_pct=50.0,
            stop_loss_pct=50.0,
            ta_signals=signals,
            close_prices=closes,
        )

        self.assertEqual(row["trades"], 1)
        self.assertEqual(row["total_return_pct"], "4.00")
        self.assertEqual(row["win_rate_pct"], "100.00")

    def test_buy_signal_reenters_after_position_was_sold(self):
        closes = [100.0] * MIN_CANDLES_FOR_TA + [100.0, 102.0, 104.0, 104.0, 110.0, 114.0]
        ta_df = _make_ta_df(closes)
        signals = ["HOLD"] * len(ta_df)
        signals[MIN_CANDLES_FOR_TA] = "BUY"
        signals[MIN_CANDLES_FOR_TA + 2] = "SELL"
        signals[MIN_CANDLES_FOR_TA + 3] = "BUY"

        row = self.optimizer._simulate_parameters(
            "BTC",
            ta_df,
            take_profit_pct=50.0,
            stop_loss_pct=50.0,
            ta_signals=signals,
            close_prices=closes,
        )

        self.assertEqual(row["trades"], 2)
        self.assertEqual(row["total_return_pct"], "14.00")
        self.assertEqual(row["win_rate_pct"], "100.00")

    def test_is_better_prefers_higher_return_then_lower_drawdown(self):
        current = {
            "total_return_pct": "5.00",
            "max_drawdown_pct": "10.00",
            "trades": 1,
        }
        candidate = {
            "total_return_pct": "5.00",
            "max_drawdown_pct": "4.00",
            "trades": 1,
        }

        self.assertTrue(self.optimizer._is_better(candidate, current))

    def test_run_writes_one_best_row_per_currency(self):
        cfg = _make_cfg(self.tmp, currencies=["BTC", "ETH"])
        _write_history_csv(self.tmp, "BTC", [100.0 + i for i in range(MIN_CANDLES_FOR_TA + 5)])
        _write_history_csv(self.tmp, "ETH", [200.0 + i for i in range(MIN_CANDLES_FOR_TA + 5)])

        optimizer = OptimizeRiskParameters(cfg)
        success = optimizer.run()

        self.assertTrue(success)
        output_file = Path(self.tmp) / "output" / "risk_optimization" / "risk_parameters.csv"
        self.assertTrue(output_file.exists())

        df = pd.read_csv(output_file)
        self.assertEqual(set(df["currency"]), {"BTC", "ETH"})
        self.assertEqual(
            list(df.columns),
            [
                "currency",
                "take_profit_percentage",
                "stop_loss_percentage",
                "total_return_pct",
                "trades",
                "win_rate_pct",
                "max_drawdown_pct",
            ],
        )


if __name__ == "__main__":
    unittest.main()

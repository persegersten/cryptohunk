#!/usr/bin/env python3
"""
Tests for RebalancePortfolio module.

These tests validate that the portfolio rebalancing logic works correctly:
- Signal generation based on TA scores and portfolio rules
- Multiple BUY recommendations allowed
- Multiple SELL recommendations
- Rule 1: holdings >= TRADE_THRESHOLD AND profit > take_profit_percentage -> SELL
- Rule 2: holdings >= TRADE_THRESHOLD AND loss > stop_loss_percentage -> SELL (overrides TA)
- Rule 3: holdings < TRADE_THRESHOLD -> no SELL
- TA is calculated for all configured currencies, even those without holdings
- Priority-based sorting
"""
import unittest
import tempfile
import shutil
from pathlib import Path
import pandas as pd
import csv
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.rebalance_portfolio import RebalancePortfolio
from src.config import Config


class TestRebalancePortfolio(unittest.TestCase):
    """Tests for RebalancePortfolio class."""

    def setUp(self):
        """Create temporary test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.data_root = Path(self.test_dir)
        
        # Create necessary directories
        self.ta_dir = self.data_root / "ta"
        self.summarised_dir = self.data_root / "summarised"
        self.output_dir = self.data_root / "output" / "rebalance"
        
        self.ta_dir.mkdir(parents=True, exist_ok=True)
        self.summarised_dir.mkdir(parents=True, exist_ok=True)

        # Create mock config
        self.cfg = Config(
            currencies=["BTC", "ETH", "SOL"],
            binance_secret="test_secret",
            binance_key="test_key",
            binance_base_url="https://api.binance.com",
            binance_currency_history_endpoint="/api/v3/klines",
            binance_exchange_info_endpoint="/api/v3/exchangeInfo",
            binance_my_trades_endpoint="/api/v3/myTrades",
            binance_trading_url="https://api.binance.com/api/v3/order",
            dry_run=True,
            data_area_root_dir=str(self.data_root),
            currency_history_period="1h",
            currency_history_nof_elements=300,
            trade_threshold=100.0,  # 100 USDC threshold
            take_profit_percentage=10.0,  # 10% take profit
            stop_loss_percentage=6.0,  # 6% stop loss
            allowed_quote_assets=["USDT"],
            ftp_host=None,
            ftp_dir=None,
            ftp_username=None,
            ftp_password=None,
            ftp_html_regexp=None,
            raw_env={}
        )

    def tearDown(self):
        """Clean up temporary test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_ta_file(self, currency: str, rsi: float, ema_12: float, ema_26: float,
                        macd: float, macd_signal: float, close: float, ema_200: float,
                        ema_21: float = None, ema_50: float = None, n_rows: int = 20,
                        rsi_prev: float = None, rsi_lookback_min: float = None,
                        macd_prev: float = None, macd_signal_prev: float = None):
        """Create a TA CSV file for testing.

        Creates enough rows for the TA2 strategy (at least 2 rows needed).
        When macd_prev/macd_signal_prev are provided, they set the MACD values
        at t-1 to control the bullish MACD cross condition.
        """
        ta_file = self.ta_dir / f"{currency}_ta.csv"

        if ema_21 is None:
            ema_21 = close - 100  # default: close > ema_21
        if ema_50 is None:
            ema_50 = ema_200 + 500
        if macd_prev is None:
            macd_prev = macd_signal - 1  # default: satisfies MACD cross (prev <= signal)
        if macd_signal_prev is None:
            macd_signal_prev = macd_signal  # default: same signal at t-1

        data = {
            'Open_Time_ms': [1000000 + i * 3600000 for i in range(n_rows)],
            'Close_Time_ms': [1000000 + i * 3600000 + 3599999 for i in range(n_rows)],
            'Close': [close] * n_rows,
            'RSI_14': [rsi] * n_rows,
            'EMA_12': [ema_12] * n_rows,
            'EMA_21': [ema_21] * n_rows,
            'EMA_26': [ema_26] * n_rows,
            'EMA_50': [ema_50] * n_rows,
            'EMA_200': [ema_200] * n_rows,
            'MACD': [macd] * n_rows,
            'MACD_Signal': [macd_signal] * n_rows,
            'MACD_Histogram': [macd - macd_signal] * n_rows,
        }
        df = pd.DataFrame(data)
        # Set previous candle MACD values for cross detection
        df.loc[df.index[-2], 'MACD'] = macd_prev
        df.loc[df.index[-2], 'MACD_Signal'] = macd_signal_prev
        df.loc[df.index[-2], 'MACD_Histogram'] = macd_prev - macd_signal_prev
        df.to_csv(ta_file, index=False)

    def _create_portfolio_summary(self, portfolio_data: list):
        """
        Create a portfolio summary CSV file for testing.
        
        Args:
            portfolio_data: List of dicts with keys: currency, balance, current_rate_usdc,
                          current_value_usdc, previous_rate_usdc, percentage_change, value_change_usdc
        """
        portfolio_file = self.summarised_dir / "portfolio.csv"
        
        with open(portfolio_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['currency', 'balance', 'current_rate_usdc', 'current_value_usdc',
                         'previous_rate_usdc', 'percentage_change', 'value_change_usdc']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(portfolio_data)

    def test_generate_signal_buy(self):
        """Test BUY signal generation with graded score above threshold."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=6,
            current_value_usdc=500.0,
            percentage_change=5.0,
            macd_sell=False
        )
        
        self.assertEqual(signal, "BUY")
        self.assertEqual(priority, 3)  # TA-based priority

    def test_generate_signal_sell(self):
        """Test SELL signal generation via MACD exit rule."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=-4,
            current_value_usdc=500.0,
            percentage_change=5.0,
            macd_sell=True
        )
        
        self.assertEqual(signal, "SELL")
        self.assertEqual(priority, 3)  # TA-based priority

    def test_generate_signal_hold(self):
        """Test HOLD signal generation when score is below BUY threshold and no MACD sell."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=2,
            current_value_usdc=500.0,
            percentage_change=5.0,
            macd_sell=False
        )
        
        self.assertEqual(signal, "HOLD")
        self.assertEqual(priority, 3)  # TA-based priority

    def test_take_profit_does_not_sell_below_threshold(self):
        """Test Rule 3: holdings < TRADE_THRESHOLD -> no SELL even when profit exceeds Rule 1."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings < 100 USDC (TRADE_THRESHOLD) AND profit > 10%
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,  # Neutral TA
            current_value_usdc=50.0,  # < 100 USDC threshold
            percentage_change=15.0,   # > 10% profit
            macd_sell=False
        )
        
        self.assertEqual(signal, "HOLD")  # Small positions are protected from SELL
        self.assertEqual(priority, 3)  # TA-based priority

    def test_take_profit_triggers_above_threshold(self):
        """Test Rule 1: holdings >= TRADE_THRESHOLD AND profit > 10% -> SELL."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings >= 100 USDC (TRADE_THRESHOLD) AND profit > 10%
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=6,  # Bullish TA (would normally BUY)
            current_value_usdc=500.0,  # >= 100 USDC threshold
            percentage_change=15.0,    # > 10% profit
            macd_sell=False
        )
        
        self.assertEqual(signal, "SELL")  # Should force SELL (Rule 1)
        self.assertEqual(priority, 1)  # Rule 1 has highest priority

    def test_no_sell_below_threshold(self):
        """Test Rule 3: holdings < TRADE_THRESHOLD -> no SELL (even if MACD says sell)."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings < 100 USDC, bearish TA, profit < 10%
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=-4,  # Bearish TA (below BUY_THRESHOLD)
            current_value_usdc=50.0,  # < 100 USDC threshold
            percentage_change=5.0,    # < 10% profit
            macd_sell=True  # MACD exit rule triggered
        )
        
        self.assertEqual(signal, "HOLD")  # Should prevent SELL (Rule 3); ta_score too low to BUY
        self.assertEqual(priority, 3)  # TA-based priority

    def test_buy_allowed_below_threshold_despite_macd_sell(self):
        """Test Rule 3 fix: no holdings + macd_sell=True but strong ta_score -> BUY (not HOLD).

        When a currency has no holdings and macd_sell is triggered via ema21_exit
        (Close < EMA_21 while MACD is still bullish), the graded ta_score can still
        reach >= BUY_THRESHOLD. Rule 3 must only prevent SELL, not block BUY.
        """
        rebalancer = RebalancePortfolio(self.cfg)
        
        # No holdings, strong bullish ta_score, but macd_sell=True (e.g. Close < EMA_21)
        signal, priority = rebalancer._generate_signal(
            currency="ETH",
            ta_score=6,    # Score >= BUY_THRESHOLD (5)
            current_value_usdc=0.0,   # No holdings
            percentage_change=0.0,
            macd_sell=True  # Triggered via Close < EMA_21, even though MACD is bullish
        )
        
        self.assertEqual(signal, "BUY")   # Should generate BUY despite macd_sell (Rule 3 allows it)
        self.assertEqual(priority, 3)

    def test_hold_below_threshold_macd_sell_score_too_low(self):
        """Test no holdings + macd_sell=True + ta_score below BUY_THRESHOLD -> HOLD."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        signal, priority = rebalancer._generate_signal(
            currency="SOL",
            ta_score=3,    # Below BUY_THRESHOLD (5)
            current_value_usdc=0.0,
            percentage_change=0.0,
            macd_sell=True
        )
        
        self.assertEqual(signal, "HOLD")
        self.assertEqual(priority, 3)

    def test_sell_allowed_above_threshold(self):
        """Test that SELL is allowed when holdings >= TRADE_THRESHOLD and MACD says sell."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings >= 100 USDC and bearish TA
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=-4,  # Bearish TA
            current_value_usdc=150.0,  # >= 100 USDC threshold
            percentage_change=5.0,     # < 10% profit
            macd_sell=True  # MACD exit rule triggered
        )
        
        self.assertEqual(signal, "SELL")  # SELL is allowed
        self.assertEqual(priority, 3)  # TA-based priority

    def test_stop_loss_triggers_sell(self):
        """Test Rule 2: holdings >= TRADE_THRESHOLD AND loss > stop_loss_percentage -> SELL (high priority)."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings >= 100 USDC (TRADE_THRESHOLD) AND loss > 6%
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=6,  # Bullish TA (would normally BUY)
            current_value_usdc=150.0,  # >= 100 USDC threshold
            percentage_change=-7.0,  # > 6% loss (stop loss triggered)
            macd_sell=False
        )
        
        self.assertEqual(signal, "SELL")  # Should force SELL (Rule 2 stop loss)
        self.assertEqual(priority, 2)  # Rule 2 has high priority

    def test_stop_loss_not_triggered_small_loss(self):
        """Test that stop loss does not trigger for small losses below threshold."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings >= 100 USDC but loss < 6%
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=6,  # Bullish TA (score >= BUY_THRESHOLD)
            current_value_usdc=150.0,  # >= 100 USDC threshold
            percentage_change=-4.0,  # < 6% loss (stop loss NOT triggered)
            macd_sell=False
        )
        
        self.assertEqual(signal, "BUY")  # Should follow TA
        self.assertEqual(priority, 3)  # TA-based priority

    def test_stop_loss_not_triggered_below_threshold(self):
        """Test that stop loss does not apply when holdings < TRADE_THRESHOLD."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings < 100 USDC (TRADE_THRESHOLD) even with large loss
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,  # Neutral TA
            current_value_usdc=50.0,  # < 100 USDC threshold
            percentage_change=-10.0,  # Large loss (but holdings too small)
            macd_sell=False
        )
        
        self.assertEqual(signal, "HOLD")  # Stop loss doesn't apply to small holdings
        self.assertEqual(priority, 3)  # TA-based priority

    def test_multiple_buys_allowed(self):
        """Test that multiple BUY recommendations are allowed and sorted by ta_score descending."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        recommendations = [
            {'currency': 'BTC', 'ta_score': 5, 'signal': 'BUY', 
             'percentage_change': '5.00', 'priority': 3},
            {'currency': 'ETH', 'ta_score': 8, 'signal': 'BUY',
             'percentage_change': '3.00', 'priority': 3},
            {'currency': 'SOL', 'ta_score': 6, 'signal': 'BUY',
             'percentage_change': '2.00', 'priority': 3},
        ]
        
        final = rebalancer._select_final_recommendations(recommendations)
        
        # Should keep all 3 BUYs, sorted by ta_score descending
        self.assertEqual(len(final), 3)
        self.assertEqual(final[0]['currency'], 'ETH')  # Highest score (8)
        self.assertEqual(final[0]['ta_score'], 8)
        self.assertEqual(final[1]['currency'], 'SOL')  # Second highest (6)
        self.assertEqual(final[1]['ta_score'], 6)
        self.assertEqual(final[2]['currency'], 'BTC')  # Lowest (5)
        self.assertEqual(final[2]['ta_score'], 5)

    def test_sort_by_priority_then_score(self):
        """Test that recommendations are sorted by priority, then by ta_score within signal type."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        recommendations = [
            {'currency': 'BTC', 'ta_score': 6, 'signal': 'BUY',
             'percentage_change': '5.00', 'priority': 3},
            {'currency': 'ETH', 'ta_score': -3, 'signal': 'SELL',
             'percentage_change': '12.00', 'priority': 1},  # Rule 1 priority
            {'currency': 'SOL', 'ta_score': -5, 'signal': 'SELL',
             'percentage_change': '-5.00', 'priority': 3},  # TA-based
        ]
        
        final = rebalancer._select_final_recommendations(recommendations)
        
        # ETH should come first (priority 1 - Rule 1), then BTC (BUY, priority 3), then SOL (SELL, priority 3)
        self.assertEqual(len(final), 3)
        self.assertEqual(final[0]['currency'], 'ETH')  # Priority 1
        self.assertEqual(final[0]['priority'], 1)
        # BTC (BUY) before SOL (SELL) within same priority 3
        self.assertEqual(final[1]['currency'], 'BTC')
        self.assertEqual(final[2]['currency'], 'SOL')

    def test_multiple_sell_allowed(self):
        """Test that multiple SELL recommendations are allowed and sorted by ta_score ascending (most bearish first)."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        recommendations = [
            {'currency': 'BTC', 'ta_score': -4, 'signal': 'SELL',
             'percentage_change': '-5.00', 'priority': 2},
            {'currency': 'ETH', 'ta_score': -7, 'signal': 'SELL',
             'percentage_change': '-8.00', 'priority': 2},
            {'currency': 'SOL', 'ta_score': -2, 'signal': 'SELL',
             'percentage_change': '-3.00', 'priority': 2},
        ]
        
        final = rebalancer._select_final_recommendations(recommendations)
        
        # Should keep all 3 SELL signals, sorted by ta_score ascending (most bearish first)
        self.assertEqual(len(final), 3)
        self.assertEqual(final[0]['currency'], 'ETH')  # Most bearish (-7)
        self.assertEqual(final[1]['currency'], 'BTC')  # Second most bearish (-4)
        self.assertEqual(final[2]['currency'], 'SOL')  # Least bearish (-2)

    def test_full_pipeline_with_recommendations(self):
        """Test full rebalancing pipeline with TA2 strategy."""
        # Create TA files that satisfy TA2 conditions
        # BTC: BUY signal (all TA2 conditions met: Close > EMA_200, MACD cross,
        #       Close > EMA_21)
        self._create_ta_file(
            currency="BTC",
            rsi=52.0, ema_12=50100.0, ema_26=50000.0,
            macd=10.0, macd_signal=5.0, close=51000.0, ema_200=50000.0,
            ema_21=50500.0
        )  # BUY signal (graded ta_score = 6: trend+momentum+cross+RSI)
        
        # ETH: BUY signal (same conditions met)
        self._create_ta_file(
            currency="ETH",
            rsi=52.0, ema_12=3100.0, ema_26=3050.0,
            macd=5.0, macd_signal=3.0, close=3150.0, ema_200=3000.0,
            ema_21=3100.0
        )  # BUY signal (graded ta_score = 6)
        
        # SOL: SELL signal (MACD < MACD_Signal)
        self._create_ta_file(
            currency="SOL",
            rsi=45.0, ema_12=140.0, ema_26=145.0,
            macd=-5.0, macd_signal=-3.0, close=138.0, ema_200=145.0,
            ema_21=140.0
        )  # SELL signal (MACD < Signal, graded ta_score = -6)
        
        # Create portfolio summary
        portfolio_data = [
            {
                'currency': 'BTC',
                'balance': '0.01000000',
                'current_rate_usdc': '51000.00000000',
                'current_value_usdc': '510.00000000',
                'previous_rate_usdc': '50000.00000000',
                'percentage_change': '2.00',
                'value_change_usdc': '10.00000000'
            },
            {
                'currency': 'ETH',
                'balance': '0.10000000',
                'current_rate_usdc': '3150.00000000',
                'current_value_usdc': '315.00000000',
                'previous_rate_usdc': '3000.00000000',
                'percentage_change': '5.00',
                'value_change_usdc': '15.00000000'
            },
            {
                'currency': 'SOL',
                'balance': '1.50000000',
                'current_rate_usdc': '138.00000000',
                'current_value_usdc': '207.00000000',
                'previous_rate_usdc': '145.00000000',
                'percentage_change': '-4.83',
                'value_change_usdc': '-10.50000000'
            },
        ]
        self._create_portfolio_summary(portfolio_data)
        
        # Run rebalancing
        rebalancer = RebalancePortfolio(self.cfg)
        success = rebalancer.run()
        
        self.assertTrue(success)
        
        # Verify output file
        output_file = self.output_dir / "recommendations.csv"
        self.assertTrue(output_file.exists())
        
        # Read and verify recommendations
        df = pd.read_csv(output_file)
        
        # Should have 3 recommendations: 2 BUYs (BTC and ETH) and 1 SELL (SOL)
        self.assertEqual(len(df), 3)
        
        # Verify all recommendations are present
        currencies = set(df['currency'].values)
        self.assertEqual(currencies, {'BTC', 'ETH', 'SOL'})
        
        # Verify signals
        buy_recs = df[df['signal'] == 'BUY']
        sell_recs = df[df['signal'] == 'SELL']
        self.assertEqual(len(buy_recs), 2)  # BTC and ETH
        self.assertEqual(len(sell_recs), 1)  # SOL

    def test_empty_recommendations(self):
        """Test handling of no recommendations (all HOLD)."""
        # Create TA files with HOLD signals (MACD == MACD_Signal → HOLD in TA2)
        for currency in ["BTC", "ETH", "SOL"]:
            self._create_ta_file(
                currency=currency,
                rsi=50.0, ema_12=50000.0, ema_26=50000.0,
                macd=5.0, macd_signal=5.0, close=50000.0, ema_200=49000.0,
                ema_21=49500.0
            )
        
        # Create portfolio summary
        portfolio_data = [
            {
                'currency': currency,
                'balance': '1.00000000',
                'current_rate_usdc': '1000.00000000',
                'current_value_usdc': '1000.00000000',
                'previous_rate_usdc': '1000.00000000',
                'percentage_change': '0.00',
                'value_change_usdc': '0.00000000'
            }
            for currency in ["BTC", "ETH", "SOL"]
        ]
        self._create_portfolio_summary(portfolio_data)
        
        # Run rebalancing
        rebalancer = RebalancePortfolio(self.cfg)
        success = rebalancer.run()
        
        self.assertTrue(success)
        
        # Verify empty output file with headers
        output_file = self.output_dir / "recommendations.csv"
        self.assertTrue(output_file.exists())
        
        df = pd.read_csv(output_file)
        self.assertEqual(len(df), 0)  # No recommendations

    def test_ta_calculated_even_without_holdings(self):
        """Test that TA is calculated for currencies without holdings to enable future BUY signals."""
        # Create TA files for both currencies with TA2 BUY conditions
        for currency in ["BTC", "ETH"]:
            self._create_ta_file(
                currency=currency,
                rsi=52.0, ema_12=50100.0, ema_26=50000.0,
                macd=10.0, macd_signal=5.0, close=51000.0, ema_200=50000.0,
                ema_21=50500.0
            )  # BUY signal (TA2 conditions met)
        
        # Create portfolio summary with one currency having no holdings
        portfolio_data = [
            {
                'currency': 'BTC',
                'balance': '0.00000000',
                'current_rate_usdc': '51000.00000000',
                'current_value_usdc': '0.00000000',  # No holdings
                'previous_rate_usdc': '50000.00000000',
                'percentage_change': '0.00',
                'value_change_usdc': '0.00000000'
            },
            {
                'currency': 'ETH',
                'balance': '0.10000000',
                'current_rate_usdc': '3150.00000000',
                'current_value_usdc': '315.00000000',  # Has holdings
                'previous_rate_usdc': '3000.00000000',
                'percentage_change': '5.00',
                'value_change_usdc': '15.00000000'
            },
        ]
        self._create_portfolio_summary(portfolio_data)
        
        # Run rebalancing
        rebalancer = RebalancePortfolio(self.cfg)
        success = rebalancer.run()
        
        self.assertTrue(success)
        
        # Verify output file
        output_file = self.output_dir / "recommendations.csv"
        self.assertTrue(output_file.exists())
        
        # Read and verify recommendations
        df = pd.read_csv(output_file)
        
        # Should have 2 BUY recommendations: both BTC (no holdings) and ETH (with holdings)
        self.assertEqual(len(df), 2)
        # Both should have BUY signals (graded ta_score >= BUY_THRESHOLD)
        btc_rec = df[df['currency'] == 'BTC']
        eth_rec = df[df['currency'] == 'ETH']
        self.assertEqual(len(btc_rec), 1)
        self.assertEqual(len(eth_rec), 1)
        self.assertEqual(btc_rec.iloc[0]['signal'], 'BUY')
        self.assertEqual(eth_rec.iloc[0]['signal'], 'BUY')


if __name__ == "__main__":
    unittest.main()

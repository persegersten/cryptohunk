#!/usr/bin/env python3
"""
Tests for RebalancePortfolio module.

These tests validate that the portfolio rebalancing logic works correctly:
- TA score calculation
- Signal generation based on TA scores and portfolio rules
- Multiple BUY recommendations allowed
- Multiple SELL recommendations
- Rule 1: holdings < TRADE_THRESHOLD AND profit > TAKE_PROFIT_THRESHOLD -> SELL (overrides TA)
- Rule 2: holdings < TRADE_THRESHOLD AND loss > STOP_LOSS_THRESHOLD -> SELL (overrides TA)
- Rule 3: holdings < TRADE_THRESHOLD -> no SELL (unless Rule 1 or 2 applies)
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
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hunk2.src.rebalance_portfolio import RebalancePortfolio
from hunk2.src.config import Config


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
            allowed_quote_assets=["USDT"],
            take_profit_threshold=10.0,  # 10% take profit
            stop_loss_threshold=6.0,  # 6% stop loss
            raw_env={}
        )

    def tearDown(self):
        """Clean up temporary test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_ta_file(self, currency: str, rsi: float, ema_12: float, ema_26: float,
                        macd: float, macd_signal: float, close: float, ema_200: float):
        """Create a TA CSV file for testing."""
        currency_dir = self.ta_dir / currency
        currency_dir.mkdir(parents=True, exist_ok=True)
        
        ta_file = currency_dir / f"{currency}_ta.csv"
        data = {
            'Open_Time_ms': [1000000, 1001000, 1002000],
            'Close_Time_ms': [1000999, 1001999, 1002999],
            'Close': [close - 100, close - 50, close],
            'RSI_14': [50.0, 50.0, rsi],
            'EMA_12': [ema_12 - 10, ema_12 - 5, ema_12],
            'EMA_26': [ema_26 - 10, ema_26 - 5, ema_26],
            'EMA_200': [ema_200 - 10, ema_200 - 5, ema_200],
            'MACD': [macd - 1, macd - 0.5, macd],
            'MACD_Signal': [macd_signal - 1, macd_signal - 0.5, macd_signal],
            'MACD_Histogram': [0, 0, macd - macd_signal]
        }
        df = pd.DataFrame(data)
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

    def test_calculate_ta_score_buy_signal(self):
        """Test TA score calculation for strong BUY signal."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Create last row with bullish indicators
        last_row = pd.Series({
            'RSI_14': 25.0,        # < 30: +1
            'EMA_12': 50100.0,     # > EMA_26: +1
            'EMA_26': 50000.0,
            'MACD': 10.0,          # > Signal: +1
            'MACD_Signal': 5.0,
            'Close': 51000.0,      # > EMA_200: +1
            'EMA_200': 50000.0
        })
        
        score = rebalancer._calculate_ta_score(last_row)
        self.assertEqual(score, 4)  # All bullish: +4

    def test_calculate_ta_score_sell_signal(self):
        """Test TA score calculation for strong SELL signal."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Create last row with bearish indicators
        last_row = pd.Series({
            'RSI_14': 75.0,        # > 70: -1
            'EMA_12': 49900.0,     # < EMA_26: -1
            'EMA_26': 50000.0,
            'MACD': -10.0,         # < Signal: -1
            'MACD_Signal': -5.0,
            'Close': 49000.0,      # < EMA_200: -1
            'EMA_200': 50000.0
        })
        
        score = rebalancer._calculate_ta_score(last_row)
        self.assertEqual(score, -4)  # All bearish: -4

    def test_calculate_ta_score_neutral(self):
        """Test TA score calculation for neutral signal."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Create last row with neutral indicators
        last_row = pd.Series({
            'RSI_14': 50.0,        # Neutral: 0
            'EMA_12': 50000.0,     # = EMA_26: 0
            'EMA_26': 50000.0,
            'MACD': 5.0,           # = MACD_Signal: 0
            'MACD_Signal': 5.0,    
            'Close': 50000.0,      # = EMA_200: 0
            'EMA_200': 50000.0
        })
        
        score = rebalancer._calculate_ta_score(last_row)
        self.assertEqual(score, 0)  # Neutral

    def test_generate_signal_buy(self):
        """Test BUY signal generation."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=2,
            current_value_usdc=500.0,
            percentage_change=5.0
        )
        
        self.assertEqual(signal, "BUY")
        self.assertEqual(priority, 3)  # TA-based priority

    def test_generate_signal_sell(self):
        """Test SELL signal generation."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=-2,
            current_value_usdc=500.0,
            percentage_change=5.0
        )
        
        self.assertEqual(signal, "SELL")
        self.assertEqual(priority, 3)  # TA-based priority

    def test_generate_signal_hold(self):
        """Test HOLD signal generation."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,
            current_value_usdc=500.0,
            percentage_change=5.0
        )
        
        self.assertEqual(signal, "HOLD")
        self.assertEqual(priority, 3)  # TA-based priority

    def test_override_sell_with_profit_above_10_percent(self):
        """Test Rule 1: holdings < TRADE_THRESHOLD AND profit > 10% -> SELL (highest priority)."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings < 100 USDC (TRADE_THRESHOLD) AND profit > 10%
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,  # Neutral TA
            current_value_usdc=50.0,  # < 100 USDC threshold
            percentage_change=15.0    # > 10% profit
        )
        
        self.assertEqual(signal, "SELL")  # Should force SELL (Rule 1)
        self.assertEqual(priority, 1)  # Rule 1 has highest priority

    def test_no_sell_below_threshold(self):
        """Test Rule 3: holdings < TRADE_THRESHOLD -> no SELL (even if TA says sell)."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings < 100 USDC and profit < 10%
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=-2,  # Bearish TA (would normally SELL)
            current_value_usdc=50.0,  # < 100 USDC threshold
            percentage_change=5.0     # < 10% profit
        )
        
        self.assertEqual(signal, "HOLD")  # Should prevent SELL (Rule 3)
        self.assertEqual(priority, 3)  # TA-based priority

    def test_sell_allowed_above_threshold(self):
        """Test that SELL is allowed when holdings >= TRADE_THRESHOLD and TA says sell."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings >= 100 USDC and bearish TA
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=-2,  # Bearish TA
            current_value_usdc=150.0,  # >= 100 USDC threshold
            percentage_change=5.0      # < 10% profit
        )
        
        self.assertEqual(signal, "SELL")  # SELL is allowed
        self.assertEqual(priority, 3)  # TA-based priority

    def test_multiple_buys_allowed(self):
        """Test that multiple BUY recommendations are allowed."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        recommendations = [
            {'currency': 'BTC', 'ta_score': 2, 'signal': 'BUY', 
             'percentage_change': '5.00', 'priority': 3, 'abs_ta_score': 2},
            {'currency': 'ETH', 'ta_score': 3, 'signal': 'BUY',
             'percentage_change': '3.00', 'priority': 3, 'abs_ta_score': 3},
            {'currency': 'SOL', 'ta_score': 1, 'signal': 'BUY',
             'percentage_change': '2.00', 'priority': 3, 'abs_ta_score': 1},
        ]
        
        final = rebalancer._select_final_recommendations(recommendations)
        
        # Should keep all 3 BUYs, sorted by abs_ta_score descending
        self.assertEqual(len(final), 3)
        self.assertEqual(final[0]['currency'], 'ETH')  # Highest score
        self.assertEqual(final[0]['ta_score'], 3)
        self.assertEqual(final[1]['currency'], 'BTC')  # Second highest
        self.assertEqual(final[1]['ta_score'], 2)
        self.assertEqual(final[2]['currency'], 'SOL')  # Lowest
        self.assertEqual(final[2]['ta_score'], 1)

    def test_sort_by_priority_then_abs_score(self):
        """Test that recommendations are sorted by priority, then by absolute TA score."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        recommendations = [
            {'currency': 'BTC', 'ta_score': 2, 'signal': 'BUY',
             'percentage_change': '5.00', 'priority': 3, 'abs_ta_score': 2},
            {'currency': 'ETH', 'ta_score': -3, 'signal': 'SELL',
             'percentage_change': '12.00', 'priority': 1, 'abs_ta_score': 3},  # Rule 1 priority
            {'currency': 'SOL', 'ta_score': -2, 'signal': 'SELL',
             'percentage_change': '-5.00', 'priority': 3, 'abs_ta_score': 2},  # TA-based
        ]
        
        final = rebalancer._select_final_recommendations(recommendations)
        
        # ETH should come first (priority 1 - Rule 1), then BTC and SOL by abs_ta_score
        self.assertEqual(len(final), 3)
        self.assertEqual(final[0]['currency'], 'ETH')  # Priority 1
        self.assertEqual(final[0]['priority'], 1)
        # BTC and SOL both have priority 3 and abs_ta_score 2, so stable sort keeps original order
        self.assertEqual(final[1]['currency'], 'BTC')
        self.assertEqual(final[2]['currency'], 'SOL')

    def test_multiple_sell_allowed(self):
        """Test that multiple SELL recommendations are allowed."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        recommendations = [
            {'currency': 'BTC', 'ta_score': -2, 'signal': 'SELL',
             'percentage_change': '-5.00', 'priority': 3, 'abs_ta_score': 2},
            {'currency': 'ETH', 'ta_score': -3, 'signal': 'SELL',
             'percentage_change': '-8.00', 'priority': 3, 'abs_ta_score': 3},
            {'currency': 'SOL', 'ta_score': -1, 'signal': 'SELL',
             'percentage_change': '-3.00', 'priority': 3, 'abs_ta_score': 1},
        ]
        
        final = rebalancer._select_final_recommendations(recommendations)
        
        # Should keep all 3 SELL signals, sorted by abs_ta_score descending
        self.assertEqual(len(final), 3)
        self.assertEqual(final[0]['currency'], 'ETH')  # Highest abs score
        self.assertEqual(final[1]['currency'], 'BTC')  # Second highest
        self.assertEqual(final[2]['currency'], 'SOL')  # Lowest

    def test_full_pipeline_with_recommendations(self):
        """Test full rebalancing pipeline."""
        # Create TA files
        self._create_ta_file(
            currency="BTC",
            rsi=25.0, ema_12=50100.0, ema_26=50000.0,
            macd=10.0, macd_signal=5.0, close=51000.0, ema_200=50000.0
        )  # Strong BUY signal (score = 4)
        
        self._create_ta_file(
            currency="ETH",
            rsi=35.0, ema_12=3100.0, ema_26=3050.0,
            macd=5.0, macd_signal=3.0, close=3150.0, ema_200=3100.0
        )  # Weak BUY signal (score = 3)
        
        self._create_ta_file(
            currency="SOL",
            rsi=75.0, ema_12=140.0, ema_26=145.0,
            macd=-5.0, macd_signal=-3.0, close=138.0, ema_200=145.0
        )  # Strong SELL signal (score = -4)
        
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
        # Sorted by abs_ta_score: BTC (4), ETH (3), SOL (4)
        self.assertEqual(len(df), 3)
        
        # Verify all recommendations are present
        currencies = set(df['currency'].values)
        self.assertEqual(currencies, {'BTC', 'ETH', 'SOL'})
        
        # Verify signals
        buy_recs = df[df['signal'] == 'BUY']
        sell_recs = df[df['signal'] == 'SELL']
        self.assertEqual(len(buy_recs), 2)  # BTC and ETH
        self.assertEqual(len(sell_recs), 1)  # SOL
        
        # Verify sorting by abs_ta_score (BTC=4, SOL=-4, ETH=3)
        # Both BTC and SOL have abs score 4, so BTC comes first (stable sort)
        self.assertEqual(df.iloc[0]['currency'], 'BTC')
        self.assertEqual(df.iloc[1]['currency'], 'SOL')
        self.assertEqual(df.iloc[2]['currency'], 'ETH')

    def test_empty_recommendations(self):
        """Test handling of no recommendations (all HOLD)."""
        # Create TA files with neutral signals
        for currency in ["BTC", "ETH", "SOL"]:
            self._create_ta_file(
                currency=currency,
                rsi=50.0, ema_12=50000.0, ema_26=50000.0,
                macd=0.0, macd_signal=0.0, close=50000.0, ema_200=50000.0
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
        # Create TA files for both currencies (both should be processed now)
        for currency in ["BTC", "ETH"]:
            self._create_ta_file(
                currency=currency,
                rsi=25.0, ema_12=50100.0, ema_26=50000.0,
                macd=10.0, macd_signal=5.0, close=51000.0, ema_200=50000.0
            )  # Strong BUY signal
        
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
        # ETH should come first (higher abs_ta_score due to more data points)
        # Both should have BUY signals
        btc_rec = df[df['currency'] == 'BTC']
        eth_rec = df[df['currency'] == 'ETH']
        self.assertEqual(len(btc_rec), 1)
        self.assertEqual(len(eth_rec), 1)
        self.assertEqual(btc_rec.iloc[0]['signal'], 'BUY')
        self.assertEqual(eth_rec.iloc[0]['signal'], 'BUY')

    def test_stop_loss_with_small_holdings(self):
        """Test Rule 2: holdings < TRADE_THRESHOLD AND loss > STOP_LOSS_THRESHOLD -> SELL."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings < 100 USDC and loss > 6%
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,  # Neutral TA
            current_value_usdc=50.0,  # < 100 USDC threshold
            percentage_change=-8.0    # > 6% loss (negative)
        )
        
        self.assertEqual(signal, "SELL")  # Should force SELL (Rule 2)
        self.assertEqual(priority, 2)  # Rule 2 has second priority

    def test_stop_loss_exactly_at_threshold(self):
        """Test stop loss at exactly the threshold value."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings < 100 USDC and loss exactly at 6%
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=2,  # Bullish TA (would normally BUY)
            current_value_usdc=50.0,  # < 100 USDC threshold
            percentage_change=-6.0    # exactly at 6% loss
        )
        
        # At exactly -6%, should NOT trigger stop loss (< -6% means more negative)
        self.assertEqual(signal, "BUY")  # Should follow TA
        self.assertEqual(priority, 3)

    def test_stop_loss_priority_lower_than_take_profit(self):
        """Test that stop loss has lower priority than take profit."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Test take profit (Rule 1)
        signal_tp, priority_tp = rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,
            current_value_usdc=50.0,
            percentage_change=15.0  # > 10% profit
        )
        
        # Test stop loss (Rule 2)
        signal_sl, priority_sl = rebalancer._generate_signal(
            currency="ETH",
            ta_score=0,
            current_value_usdc=50.0,
            percentage_change=-8.0  # > 6% loss
        )
        
        self.assertEqual(signal_tp, "SELL")
        self.assertEqual(priority_tp, 1)  # Take profit is priority 1
        self.assertEqual(signal_sl, "SELL")
        self.assertEqual(priority_sl, 2)  # Stop loss is priority 2

    def test_configurable_thresholds(self):
        """Test that thresholds can be configured via Config object."""
        # Create a custom config with different thresholds
        custom_cfg = Config(
            currencies=["BTC"],
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
            trade_threshold=100.0,
            allowed_quote_assets=["USDT"],
            take_profit_threshold=15.0,  # Custom 15% take profit
            stop_loss_threshold=8.0,  # Custom 8% stop loss
            raw_env={}
        )
        
        rebalancer = RebalancePortfolio(custom_cfg)
        
        # Test custom take profit threshold
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,
            current_value_usdc=50.0,
            percentage_change=12.0  # Between 10% and 15%
        )
        # Should NOT trigger take profit (< 15%)
        self.assertEqual(signal, "HOLD")
        
        # Test that 16% DOES trigger take profit
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,
            current_value_usdc=50.0,
            percentage_change=16.0  # > 15%
        )
        self.assertEqual(signal, "SELL")
        self.assertEqual(priority, 1)
        
        # Test custom stop loss threshold
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,
            current_value_usdc=50.0,
            percentage_change=-7.0  # Between -6% and -8%
        )
        # Should NOT trigger stop loss (> -8%)
        self.assertEqual(signal, "HOLD")
        
        # Test that -9% DOES trigger stop loss
        signal, priority = rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,
            current_value_usdc=50.0,
            percentage_change=-9.0  # < -8%
        )
        self.assertEqual(signal, "SELL")
        self.assertEqual(priority, 2)


if __name__ == "__main__":
    unittest.main()

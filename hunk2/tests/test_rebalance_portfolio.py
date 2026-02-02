#!/usr/bin/env python3
"""
Tests for RebalancePortfolio module.

These tests validate that the portfolio rebalancing logic works correctly:
- TA score calculation
- Signal generation based on TA scores and portfolio rules
- Max 1 BUY recommendation selection
- Multiple SELL recommendations
- Override rules for TRADE_THRESHOLD and profit > 10%
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
            'MACD': 5.0,           # = Signal: 0
            'MACD_Signal': 5.0,    # = MACD: 0
            'Close': 50000.0,      # = EMA_200: 0
            'EMA_200': 50000.0
        })
        
        score = rebalancer._calculate_ta_score(last_row)
        self.assertEqual(score, 0)  # Neutral

    def test_generate_signal_buy(self):
        """Test BUY signal generation."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        signal = rebalancer._generate_signal(
            currency="BTC",
            ta_score=2,
            current_value_usdc=500.0,
            percentage_change=5.0
        )
        
        self.assertEqual(signal, "BUY")

    def test_generate_signal_sell(self):
        """Test SELL signal generation."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        signal = rebalancer._generate_signal(
            currency="BTC",
            ta_score=-2,
            current_value_usdc=500.0,
            percentage_change=5.0
        )
        
        self.assertEqual(signal, "SELL")

    def test_generate_signal_hold(self):
        """Test HOLD signal generation."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        signal = rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,
            current_value_usdc=500.0,
            percentage_change=5.0
        )
        
        self.assertEqual(signal, "HOLD")

    def test_override_sell_with_profit_above_threshold(self):
        """Test override rule: holdings < TRADE_THRESHOLD but profit > 10% -> SELL."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings < 100 USDC (TRADE_THRESHOLD) but profit > 10%
        signal = rebalancer._generate_signal(
            currency="BTC",
            ta_score=0,  # Neutral TA
            current_value_usdc=50.0,  # < 100 USDC threshold
            percentage_change=15.0    # > 10% profit
        )
        
        self.assertEqual(signal, "SELL")  # Should force SELL

    def test_no_sell_below_threshold(self):
        """Test rule: holdings < TRADE_THRESHOLD -> no SELL."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        # Holdings < 100 USDC and profit < 10%
        signal = rebalancer._generate_signal(
            currency="BTC",
            ta_score=-2,  # Bearish TA (would normally SELL)
            current_value_usdc=50.0,  # < 100 USDC threshold
            percentage_change=5.0     # < 10% profit
        )
        
        self.assertEqual(signal, "HOLD")  # Should prevent SELL

    def test_select_max_one_buy(self):
        """Test that only 1 BUY is selected (highest score)."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        recommendations = [
            {'currency': 'BTC', 'ta_score': 2, 'signal': 'BUY', 
             'current_value_usdc': '500.00', 'percentage_change': '5.00'},
            {'currency': 'ETH', 'ta_score': 3, 'signal': 'BUY',
             'current_value_usdc': '300.00', 'percentage_change': '3.00'},
            {'currency': 'SOL', 'ta_score': 1, 'signal': 'BUY',
             'current_value_usdc': '200.00', 'percentage_change': '2.00'},
        ]
        
        final = rebalancer._select_final_recommendations(recommendations)
        
        # Should select only ETH (highest score = 3)
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]['currency'], 'ETH')
        self.assertEqual(final[0]['ta_score'], 3)

    def test_select_first_buy_on_tie(self):
        """Test that first BUY is selected when scores are tied."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        recommendations = [
            {'currency': 'BTC', 'ta_score': 2, 'signal': 'BUY',
             'current_value_usdc': '500.00', 'percentage_change': '5.00'},
            {'currency': 'ETH', 'ta_score': 2, 'signal': 'BUY',
             'current_value_usdc': '300.00', 'percentage_change': '3.00'},
        ]
        
        final = rebalancer._select_final_recommendations(recommendations)
        
        # Should select BTC (first with score 2)
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]['currency'], 'BTC')

    def test_multiple_sell_allowed(self):
        """Test that multiple SELL recommendations are allowed."""
        rebalancer = RebalancePortfolio(self.cfg)
        
        recommendations = [
            {'currency': 'BTC', 'ta_score': -2, 'signal': 'SELL',
             'current_value_usdc': '500.00', 'percentage_change': '-5.00'},
            {'currency': 'ETH', 'ta_score': -3, 'signal': 'SELL',
             'current_value_usdc': '300.00', 'percentage_change': '-8.00'},
            {'currency': 'SOL', 'ta_score': -1, 'signal': 'SELL',
             'current_value_usdc': '200.00', 'percentage_change': '-3.00'},
        ]
        
        final = rebalancer._select_final_recommendations(recommendations)
        
        # Should keep all 3 SELL signals
        self.assertEqual(len(final), 3)
        sell_currencies = {r['currency'] for r in final}
        self.assertEqual(sell_currencies, {'BTC', 'ETH', 'SOL'})

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
        
        # Should have 2 recommendations: 1 BUY (BTC with highest score) and 1 SELL (SOL)
        self.assertEqual(len(df), 2)
        
        # Verify BTC is selected (highest BUY score)
        buy_rec = df[df['signal'] == 'BUY']
        self.assertEqual(len(buy_rec), 1)
        self.assertEqual(buy_rec.iloc[0]['currency'], 'BTC')
        
        # Verify SOL is SELL
        sell_rec = df[df['signal'] == 'SELL']
        self.assertEqual(len(sell_rec), 1)
        self.assertEqual(sell_rec.iloc[0]['currency'], 'SOL')

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


if __name__ == "__main__":
    unittest.main()

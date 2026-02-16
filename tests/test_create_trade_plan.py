#!/usr/bin/env python3
"""
Tests for CreateTradePlan module.

These tests validate that the trade plan generation logic works correctly:
- Reads portfolio and recommendations correctly
- Processes SELL recommendations first (only if value > TRADE_THRESHOLD)
- Calculates liquid funds correctly after SELLs
- Processes BUY recommendations (max 1, only if liquid funds > TRADE_THRESHOLD)
- Saves trade plan correctly
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

from src.create_trade_plan import CreateTradePlan
from src.config import Config


class TestCreateTradePlan(unittest.TestCase):
    """Tests for CreateTradePlan class."""

    def setUp(self):
        """Create temporary test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.data_root = Path(self.test_dir)
        
        # Create necessary directories
        self.summarised_dir = self.data_root / "summarised"
        self.output_dir = self.data_root / "output" / "rebalance"
        
        self.summarised_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

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
            raw_env={}
        )

    def tearDown(self):
        """Clean up temporary test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_portfolio_summary(self, portfolio_data: list):
        """Create a portfolio summary CSV file for testing."""
        portfolio_file = self.summarised_dir / "portfolio.csv"
        
        with open(portfolio_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['currency', 'balance', 'current_rate_usdc', 'current_value_usdc',
                         'previous_rate_usdc', 'percentage_change', 'value_change_usdc']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(portfolio_data)

    def _create_recommendations(self, recommendations_data: list):
        """Create a recommendations CSV file for testing."""
        recommendations_file = self.output_dir / "recommendations.csv"
        
        with open(recommendations_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['currency', 'percentage_change', 'ta_score', 'signal']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(recommendations_data)

    def _read_trade_plan(self) -> list:
        """Read the generated trade plan."""
        trade_plan_file = self.output_dir / "trade_plan.csv"
        
        with open(trade_plan_file, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return list(reader)

    def test_sell_above_threshold(self):
        """Test SELL when value exceeds threshold."""
        # Create portfolio with BTC above threshold
        portfolio = [
            {'currency': 'USDC', 'balance': 50.0, 'current_rate_usdc': 1.0, 
             'current_value_usdc': 50.0, 'previous_rate_usdc': 1.0,
             'percentage_change': 0.0, 'value_change_usdc': 0.0},
            {'currency': 'BTC', 'balance': 0.005, 'current_rate_usdc': 50000.0, 
             'current_value_usdc': 250.0, 'previous_rate_usdc': 49000.0,
             'percentage_change': 2.04, 'value_change_usdc': 5.0}
        ]
        self._create_portfolio_summary(portfolio)
        
        # Create SELL recommendation for BTC
        recommendations = [
            {'currency': 'BTC', 'percentage_change': '2.04', 'ta_score': -2, 'signal': 'SELL'}
        ]
        self._create_recommendations(recommendations)
        
        # Generate trade plan
        creator = CreateTradePlan(self.cfg)
        success = creator.run()
        
        self.assertTrue(success)
        
        # Verify trade plan
        trade_plan = self._read_trade_plan()
        self.assertEqual(len(trade_plan), 1)
        self.assertEqual(trade_plan[0]['action'], 'SELL')
        self.assertEqual(trade_plan[0]['currency'], 'BTC')
        self.assertEqual(float(trade_plan[0]['amount']), 0.005)
        self.assertEqual(float(trade_plan[0]['value_usdc']), 250.0)

    def test_sell_below_threshold_skipped(self):
        """Test SELL skipped when value is below threshold."""
        # Create portfolio with BTC below threshold
        portfolio = [
            {'currency': 'USDC', 'balance': 50.0, 'current_rate_usdc': 1.0, 
             'current_value_usdc': 50.0, 'previous_rate_usdc': 1.0,
             'percentage_change': 0.0, 'value_change_usdc': 0.0},
            {'currency': 'BTC', 'balance': 0.001, 'current_rate_usdc': 50000.0, 
             'current_value_usdc': 50.0, 'previous_rate_usdc': 49000.0,
             'percentage_change': 2.04, 'value_change_usdc': 1.0}
        ]
        self._create_portfolio_summary(portfolio)
        
        # Create SELL recommendation for BTC
        recommendations = [
            {'currency': 'BTC', 'percentage_change': '2.04', 'ta_score': -2, 'signal': 'SELL'}
        ]
        self._create_recommendations(recommendations)
        
        # Generate trade plan
        creator = CreateTradePlan(self.cfg)
        success = creator.run()
        
        self.assertTrue(success)
        
        # Verify trade plan is empty (SELL was skipped)
        trade_plan = self._read_trade_plan()
        self.assertEqual(len(trade_plan), 0)

    def test_buy_with_sufficient_funds(self):
        """Test BUY when liquid funds exceed threshold."""
        # Create portfolio with sufficient USDC
        portfolio = [
            {'currency': 'USDC', 'balance': 500.0, 'current_rate_usdc': 1.0, 
             'current_value_usdc': 500.0, 'previous_rate_usdc': 1.0,
             'percentage_change': 0.0, 'value_change_usdc': 0.0},
            {'currency': 'ETH', 'balance': 0.0, 'current_rate_usdc': 3000.0, 
             'current_value_usdc': 0.0, 'previous_rate_usdc': 3000.0,
             'percentage_change': 0.0, 'value_change_usdc': 0.0}
        ]
        self._create_portfolio_summary(portfolio)
        
        # Create BUY recommendation for ETH
        recommendations = [
            {'currency': 'ETH', 'percentage_change': '0.00', 'ta_score': 2, 'signal': 'BUY'}
        ]
        self._create_recommendations(recommendations)
        
        # Generate trade plan
        creator = CreateTradePlan(self.cfg)
        success = creator.run()
        
        self.assertTrue(success)
        
        # Verify trade plan
        trade_plan = self._read_trade_plan()
        self.assertEqual(len(trade_plan), 1)
        self.assertEqual(trade_plan[0]['action'], 'BUY')
        self.assertEqual(trade_plan[0]['currency'], 'ETH')
        self.assertEqual(trade_plan[0]['amount'], 'ALL')
        self.assertEqual(float(trade_plan[0]['value_usdc']), 500.0)

    def test_buy_skipped_insufficient_funds(self):
        """Test BUY skipped when liquid funds are below threshold."""
        # Create portfolio with insufficient USDC
        portfolio = [
            {'currency': 'USDC', 'balance': 50.0, 'current_rate_usdc': 1.0, 
             'current_value_usdc': 50.0, 'previous_rate_usdc': 1.0,
             'percentage_change': 0.0, 'value_change_usdc': 0.0},
            {'currency': 'ETH', 'balance': 0.0, 'current_rate_usdc': 3000.0, 
             'current_value_usdc': 0.0, 'previous_rate_usdc': 3000.0,
             'percentage_change': 0.0, 'value_change_usdc': 0.0}
        ]
        self._create_portfolio_summary(portfolio)
        
        # Create BUY recommendation for ETH
        recommendations = [
            {'currency': 'ETH', 'percentage_change': '0.00', 'ta_score': 2, 'signal': 'BUY'}
        ]
        self._create_recommendations(recommendations)
        
        # Generate trade plan
        creator = CreateTradePlan(self.cfg)
        success = creator.run()
        
        self.assertTrue(success)
        
        # Verify trade plan is empty (BUY was skipped)
        trade_plan = self._read_trade_plan()
        self.assertEqual(len(trade_plan), 0)

    def test_multiple_sells_one_buy(self):
        """Test multiple SELLs followed by one BUY."""
        # Create portfolio
        portfolio = [
            {'currency': 'USDC', 'balance': 50.0, 'current_rate_usdc': 1.0, 
             'current_value_usdc': 50.0, 'previous_rate_usdc': 1.0,
             'percentage_change': 0.0, 'value_change_usdc': 0.0},
            {'currency': 'BTC', 'balance': 0.005, 'current_rate_usdc': 50000.0, 
             'current_value_usdc': 250.0, 'previous_rate_usdc': 49000.0,
             'percentage_change': 2.04, 'value_change_usdc': 5.0},
            {'currency': 'ETH', 'balance': 0.1, 'current_rate_usdc': 3000.0, 
             'current_value_usdc': 300.0, 'previous_rate_usdc': 2900.0,
             'percentage_change': 3.45, 'value_change_usdc': 10.0},
            {'currency': 'SOL', 'balance': 0.0, 'current_rate_usdc': 100.0, 
             'current_value_usdc': 0.0, 'previous_rate_usdc': 100.0,
             'percentage_change': 0.0, 'value_change_usdc': 0.0}
        ]
        self._create_portfolio_summary(portfolio)
        
        # Create recommendations: 2 SELLs and 2 BUYs
        recommendations = [
            {'currency': 'BTC', 'percentage_change': '2.04', 'ta_score': -2, 'signal': 'SELL'},
            {'currency': 'ETH', 'percentage_change': '3.45', 'ta_score': -3, 'signal': 'SELL'},
            {'currency': 'SOL', 'percentage_change': '0.00', 'ta_score': 3, 'signal': 'BUY'},
            {'currency': 'ADA', 'percentage_change': '0.00', 'ta_score': 2, 'signal': 'BUY'}
        ]
        self._create_recommendations(recommendations)
        
        # Generate trade plan
        creator = CreateTradePlan(self.cfg)
        success = creator.run()
        
        self.assertTrue(success)
        
        # Verify trade plan: 2 SELLs + 1 BUY
        trade_plan = self._read_trade_plan()
        self.assertEqual(len(trade_plan), 3)
        
        # Check SELLs
        sells = [t for t in trade_plan if t['action'] == 'SELL']
        self.assertEqual(len(sells), 2)
        
        # Check BUY (should be only one)
        buys = [t for t in trade_plan if t['action'] == 'BUY']
        self.assertEqual(len(buys), 1)
        self.assertEqual(buys[0]['currency'], 'SOL')
        self.assertEqual(buys[0]['amount'], 'ALL')
        # Should be: 50 (initial USDC) + 250 (BTC) + 300 (ETH) = 600
        self.assertEqual(float(buys[0]['value_usdc']), 600.0)

    def test_empty_recommendations(self):
        """Test with empty recommendations."""
        # Create portfolio
        portfolio = [
            {'currency': 'USDC', 'balance': 500.0, 'current_rate_usdc': 1.0, 
             'current_value_usdc': 500.0, 'previous_rate_usdc': 1.0,
             'percentage_change': 0.0, 'value_change_usdc': 0.0}
        ]
        self._create_portfolio_summary(portfolio)
        
        # Create empty recommendations
        self._create_recommendations([])
        
        # Generate trade plan
        creator = CreateTradePlan(self.cfg)
        success = creator.run()
        
        self.assertTrue(success)
        
        # Verify trade plan is empty
        trade_plan = self._read_trade_plan()
        self.assertEqual(len(trade_plan), 0)

    def test_liquid_funds_calculation_after_sells(self):
        """Test that liquid funds are correctly updated after SELLs."""
        # Create portfolio with some USDC and holdings to sell
        portfolio = [
            {'currency': 'USDC', 'balance': 100.0, 'current_rate_usdc': 1.0, 
             'current_value_usdc': 100.0, 'previous_rate_usdc': 1.0,
             'percentage_change': 0.0, 'value_change_usdc': 0.0},
            {'currency': 'BTC', 'balance': 0.004, 'current_rate_usdc': 50000.0, 
             'current_value_usdc': 200.0, 'previous_rate_usdc': 49000.0,
             'percentage_change': 2.04, 'value_change_usdc': 4.0},
            {'currency': 'ETH', 'balance': 0.0, 'current_rate_usdc': 3000.0, 
             'current_value_usdc': 0.0, 'previous_rate_usdc': 3000.0,
             'percentage_change': 0.0, 'value_change_usdc': 0.0}
        ]
        self._create_portfolio_summary(portfolio)
        
        # SELL BTC, then BUY ETH with proceeds
        recommendations = [
            {'currency': 'BTC', 'percentage_change': '2.04', 'ta_score': -2, 'signal': 'SELL'},
            {'currency': 'ETH', 'percentage_change': '0.00', 'ta_score': 3, 'signal': 'BUY'}
        ]
        self._create_recommendations(recommendations)
        
        # Generate trade plan
        creator = CreateTradePlan(self.cfg)
        success = creator.run()
        
        self.assertTrue(success)
        
        # Verify trade plan
        trade_plan = self._read_trade_plan()
        self.assertEqual(len(trade_plan), 2)
        
        # First should be SELL
        self.assertEqual(trade_plan[0]['action'], 'SELL')
        self.assertEqual(trade_plan[0]['currency'], 'BTC')
        self.assertEqual(float(trade_plan[0]['value_usdc']), 200.0)
        
        # Second should be BUY with combined funds (100 initial + 200 from sell)
        self.assertEqual(trade_plan[1]['action'], 'BUY')
        self.assertEqual(trade_plan[1]['currency'], 'ETH')
        self.assertEqual(float(trade_plan[1]['value_usdc']), 300.0)


if __name__ == '__main__':
    unittest.main()

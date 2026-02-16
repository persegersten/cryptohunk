#!/usr/bin/env python3
"""
Tests for ExecuteTradePlan module.

These tests validate that trade execution logic works correctly:
- Reads trade plan correctly
- Validates exchange info in both dry-run and live modes
- Executes trades in dry-run mode (logging only)
- Executes trades in live mode (with mocked CCXT broker)
"""
import unittest
import tempfile
import shutil
from pathlib import Path
import csv
import sys
from unittest.mock import MagicMock, patch, call

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.execute_trade_plan import ExecuteTradePlan, CCXTBroker
from src.config import Config


class TestExecuteTradePlan(unittest.TestCase):
    """Tests for ExecuteTradePlan class."""

    def setUp(self):
        """Create temporary test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.data_root = Path(self.test_dir)
        
        # Create necessary directories
        self.output_dir = self.data_root / "output" / "rebalance"
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
            trade_threshold=100.0,
            take_profit_percentage=10.0,  # 10% take profit
            stop_loss_percentage=6.0,  # 6% stop loss
            allowed_quote_assets=["USDT", "USDC"],
            raw_env={}
        )

    def tearDown(self):
        """Clean up temporary test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_trade_plan(self, trades: list):
        """Create a trade plan CSV file for testing."""
        trade_plan_file = self.output_dir / "trade_plan.csv"
        
        with open(trade_plan_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['action', 'currency', 'amount', 'value_usdc']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(trades)

    def test_read_trade_plan(self):
        """Test reading trade plan from file."""
        # Create test trade plan
        trades = [
            {'action': 'SELL', 'currency': 'BTC', 'amount': '0.005', 'value_usdc': '250.00'},
            {'action': 'BUY', 'currency': 'ETH', 'amount': 'ALL', 'value_usdc': '300.00'}
        ]
        self._create_trade_plan(trades)
        
        # Read trade plan
        executor = ExecuteTradePlan(self.cfg)
        read_trades = executor._read_trade_plan()
        
        self.assertIsNotNone(read_trades)
        self.assertEqual(len(read_trades), 2)
        self.assertEqual(read_trades[0]['action'], 'SELL')
        self.assertEqual(read_trades[0]['currency'], 'BTC')
        self.assertEqual(read_trades[1]['action'], 'BUY')
        self.assertEqual(read_trades[1]['currency'], 'ETH')

    def test_read_trade_plan_empty(self):
        """Test reading empty trade plan."""
        # Create empty trade plan
        self._create_trade_plan([])
        
        # Read trade plan
        executor = ExecuteTradePlan(self.cfg)
        read_trades = executor._read_trade_plan()
        
        self.assertIsNotNone(read_trades)
        self.assertEqual(len(read_trades), 0)

    def test_read_trade_plan_missing_file(self):
        """Test reading trade plan when file doesn't exist."""
        executor = ExecuteTradePlan(self.cfg)
        read_trades = executor._read_trade_plan()
        
        self.assertIsNone(read_trades)

    def test_execute_trades_dry_run(self):
        """Test executing trades in dry run mode."""
        # Create test trade plan
        trades = [
            {'action': 'SELL', 'currency': 'BTC', 'amount': '0.005', 'value_usdc': '250.00'},
            {'action': 'BUY', 'currency': 'ETH', 'amount': 'ALL', 'value_usdc': '300.00'}
        ]
        self._create_trade_plan(trades)
        
        # Execute trades in dry run mode
        self.cfg.dry_run = True
        executor = ExecuteTradePlan(self.cfg)
        success = executor.execute_trades()
        
        self.assertTrue(success)

    def test_execute_trades_live_mode(self):
        """Test executing trades in live mode with mocked broker."""
        # Create test trade plan
        trades = [
            {'action': 'SELL', 'currency': 'BTC', 'amount': '0.005', 'value_usdc': '250.00'},
            {'action': 'BUY', 'currency': 'ETH', 'amount': 'ALL', 'value_usdc': '300.00'}
        ]
        self._create_trade_plan(trades)
        
        # Set to live mode
        self.cfg.dry_run = False
        
        # Mock CCXTBroker
        with patch('src.execute_trade_plan.CCXTBroker') as MockBroker:
            mock_broker_instance = MagicMock()
            MockBroker.return_value = mock_broker_instance
            
            # Mock exchange info
            mock_broker_instance.fetch_exchange_info.return_value = [
                {'symbol': 'BTC/USDC', 'active': True},
                {'symbol': 'ETH/USDC', 'active': True}
            ]
            
            # Mock order responses
            mock_broker_instance.market_sell.return_value = {'id': 'sell_123'}
            mock_broker_instance.market_buy.return_value = {'id': 'buy_456'}
            
            # Execute trades
            executor = ExecuteTradePlan(self.cfg)
            success = executor.execute_trades()
            
            self.assertTrue(success)
            
            # Verify broker methods were called
            mock_broker_instance.fetch_exchange_info.assert_called_once()
            mock_broker_instance.market_sell.assert_called_once()
            mock_broker_instance.market_buy.assert_called_once()

    def test_execute_empty_trade_plan(self):
        """Test executing empty trade plan."""
        # Create empty trade plan
        self._create_trade_plan([])
        
        executor = ExecuteTradePlan(self.cfg)
        success = executor.execute_trades()
        
        self.assertTrue(success)

    def test_run_with_empty_trade_plan_exits_early(self):
        """Test that run() exits early when trade plan contains 0 trades."""
        # Create empty trade plan
        self._create_trade_plan([])
        
        # Mock exchange info validation to verify it's NOT called
        self.cfg.dry_run = False
        
        with patch('src.execute_trade_plan.CCXTBroker') as MockBroker:
            mock_broker_instance = MagicMock()
            MockBroker.return_value = mock_broker_instance
            
            executor = ExecuteTradePlan(self.cfg)
            success = executor.run()
            
            # Should succeed
            self.assertTrue(success)
            
            # Verify exchange info validation was NOT called (early exit)
            mock_broker_instance.fetch_exchange_info.assert_not_called()

    def test_validate_exchange_info_dry_run(self):
        """Test exchange info validation in dry run mode."""
        self.cfg.dry_run = True
        executor = ExecuteTradePlan(self.cfg)
        
        # Should succeed without calling broker
        result = executor._validate_exchange_info()
        self.assertTrue(result)

    def test_validate_exchange_info_live_mode(self):
        """Test exchange info validation in live mode."""
        self.cfg.dry_run = False
        
        with patch('src.execute_trade_plan.CCXTBroker') as MockBroker:
            mock_broker_instance = MagicMock()
            MockBroker.return_value = mock_broker_instance
            
            # Mock exchange info
            mock_broker_instance.fetch_exchange_info.return_value = [
                {'symbol': 'BTC/USDC', 'active': True}
            ]
            
            executor = ExecuteTradePlan(self.cfg)
            result = executor._validate_exchange_info()
            
            self.assertTrue(result)
            mock_broker_instance.fetch_exchange_info.assert_called_once()

    def test_execute_trade_live_with_failure(self):
        """Test handling trade execution failure in live mode."""
        # Create test trade plan
        trades = [
            {'action': 'SELL', 'currency': 'BTC', 'amount': '0.005', 'value_usdc': '250.00'}
        ]
        self._create_trade_plan(trades)
        
        self.cfg.dry_run = False
        
        with patch('src.execute_trade_plan.CCXTBroker') as MockBroker:
            mock_broker_instance = MagicMock()
            MockBroker.return_value = mock_broker_instance
            
            # Mock exchange info
            mock_broker_instance.fetch_exchange_info.return_value = [
                {'symbol': 'BTC/USDC', 'active': True}
            ]
            
            # Mock trade failure
            mock_broker_instance.market_sell.side_effect = Exception("Network error")
            
            executor = ExecuteTradePlan(self.cfg)
            success = executor.execute_trades()
            
            # Should fail due to trade error
            self.assertFalse(success)


class TestCCXTBroker(unittest.TestCase):
    """Tests for CCXTBroker class."""
    
    def test_ccxt_broker_initialization(self):
        """Test CCXTBroker initialization."""
        with patch('src.execute_trade_plan.ccxt.binance') as mock_binance:
            mock_exchange = MagicMock()
            mock_binance.return_value = mock_exchange
            
            broker = CCXTBroker(
                api_key="test_key",
                api_secret="test_secret",
                base_url="https://api.binance.com"
            )
            
            self.assertIsNotNone(broker.exchange)
            mock_binance.assert_called_once()
    
    def test_ccxt_broker_time_synchronization(self):
        """Test that CCXTBroker is initialized with time synchronization enabled."""
        with patch('src.execute_trade_plan.ccxt.binance') as mock_binance:
            mock_exchange = MagicMock()
            mock_binance.return_value = mock_exchange
            
            broker = CCXTBroker(
                api_key="test_key",
                api_secret="test_secret",
                base_url="https://api.binance.com"
            )
            
            # Verify that adjustForTimeDifference is set to True
            mock_binance.assert_called_once()
            call_args = mock_binance.call_args
            self.assertIsNotNone(call_args, "ccxt.binance should have been called")
            
            # Check if called with positional argument (dict)
            if call_args[0]:
                config_dict = call_args[0][0]
                self.assertTrue(config_dict.get('adjustForTimeDifference'), 
                              "adjustForTimeDifference should be True to fix timestamp sync issues")
            else:
                self.fail("ccxt.binance was not called with expected arguments")

    def test_trade_plan_format_requires_usdc(self):
        """
        Test documenting that trade plan format requires USDC as quote currency.
        
        The trade_plan.csv format uses 'value_usdc' column, which assumes USDC
        as the quote currency. To support other quote currencies (e.g., USDT),
        the CSV format would need to be extended with a 'quote_currency' column.
        """
        # This is a documentation test - it passes to document the limitation
        # Current trade_plan.csv format:
        # action,currency,amount,value_usdc
        # SELL,BTC,0.005,250.00
        # 
        # To support USDT, format would need to be:
        # action,currency,amount,value,quote_currency
        # SELL,BTC,0.005,250.00,USDT
        self.assertTrue(True, "Trade plan format currently requires USDC quote currency")


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""
Test that USDC is included in portfolio summary.
This test validates the fix for the issue where USDC was collected
but not added to portfolio.csv.
"""
import unittest
import tempfile
import shutil
import json
import csv
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from hunk2.src.summarize_portfolio import summarize_portfolio
from hunk2.src.config import Config


class TestUSDCInPortfolio(unittest.TestCase):
    """Test that USDC is included in portfolio summary."""

    def setUp(self):
        """Create temporary test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.data_root = Path(self.test_dir)
        
        # Create necessary directories
        self.portfolio_dir = self.data_root / "portfolio"
        self.trades_dir = self.data_root / "trades"
        self.summarised_dir = self.data_root / "summarised"
        
        self.portfolio_dir.mkdir(parents=True, exist_ok=True)
        self.trades_dir.mkdir(parents=True, exist_ok=True)
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
            trade_threshold=100.0,
            allowed_quote_assets=["USDT", "USDC"],  # USDC is in allowed_quote_assets
            raw_env={}
        )

    def tearDown(self):
        """Clean up temporary test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_portfolio_json(self, balances_data: dict):
        """Create a portfolio.json file for testing."""
        portfolio_file = self.portfolio_dir / "portfolio.json"
        
        portfolio_data = {
            "timestamp": "2024-01-01T00:00:00Z",
            "balances": balances_data,
            "saved_assets_count": len(balances_data)
        }
        
        with open(portfolio_file, 'w', encoding='utf-8') as f:
            json.dump(portfolio_data, f, indent=2)

    def _create_empty_trades(self):
        """Create an empty trades.json file."""
        trades_file = self.trades_dir / "trades.json"
        
        with open(trades_file, 'w', encoding='utf-8') as f:
            json.dump([], f)

    def _read_portfolio_csv(self) -> list:
        """Read the generated portfolio CSV."""
        csv_file = self.summarised_dir / "portfolio.csv"
        
        with open(csv_file, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return list(reader)

    def test_usdc_included_in_portfolio_summary(self):
        """Test that USDC is included in portfolio summary."""
        # Create portfolio with BTC, ETH, and USDC balances
        balances = {
            "BTC": {"free": "0.005", "locked": "0", "total": "0.005"},
            "ETH": {"free": "0.1", "locked": "0", "total": "0.1"},
            "USDC": {"free": "500.0", "locked": "0", "total": "500.0"},  # USDC balance
            "USDT": {"free": "100.0", "locked": "0", "total": "100.0"}   # USDT balance
        }
        self._create_portfolio_json(balances)
        self._create_empty_trades()
        
        # Run summarize_portfolio
        # Note: This will try to fetch rates from Binance API, which will fail in tests
        # but that's OK - we just want to verify USDC is processed
        try:
            summarize_portfolio(self.cfg)
        except Exception:
            # Expected to fail due to API calls, but CSV should still be created
            pass
        
        # Read the portfolio CSV
        portfolio_csv = self._read_portfolio_csv()
        
        # Extract currencies from CSV
        currencies_in_csv = [row['currency'] for row in portfolio_csv]
        
        # Verify that USDC and USDT are included
        self.assertIn('USDC', currencies_in_csv, 
                     "USDC should be included in portfolio.csv")
        self.assertIn('USDT', currencies_in_csv,
                     "USDT should be included in portfolio.csv")
        
        # Verify that all configured currencies are also included
        self.assertIn('BTC', currencies_in_csv)
        self.assertIn('ETH', currencies_in_csv)
        self.assertIn('SOL', currencies_in_csv)
        
        # Verify we have all expected currencies (3 from currencies + 2 from quote assets)
        self.assertEqual(len(currencies_in_csv), 5,
                        "Portfolio CSV should contain 5 currencies: BTC, ETH, SOL, USDT, USDC")
        
        print(f"✓ USDC and USDT are correctly included in portfolio.csv")
        print(f"  Currencies in CSV: {', '.join(currencies_in_csv)}")


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""
Tests for RebalancePortfolio module.

These tests validate that the rebalance portfolio functionality works correctly,
including TA signal reading, portfolio loading, scoring, and recommendation generation.
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
        
        # Define directory structure (individual tests create as needed)
        self.ta_dir = self.data_root / "ta"
        self.summarised_dir = self.data_root / "summarised"
        self.output_dir = self.data_root / "output" / "rebalance"
        
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
            trade_threshold=100.0,  # $100 threshold for testing
            allowed_quote_assets=["USDT"],
            raw_env={}
        )
    
    def tearDown(self):
        """Clean up temporary test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def _create_ta_file(self, currency: str, rsi: float = 50.0, ema_12: float = 50000.0,
                        ema_26: float = 49000.0, ema_200: float = 48000.0,
                        close: float = 51000.0, macd_histogram: float = 100.0):
        """
        Create a mock TA file with specified indicators.
        
        Args:
            currency: Currency symbol
            rsi: RSI value (0-100)
            ema_12: EMA 12 value
            ema_26: EMA 26 value
            ema_200: EMA 200 value
            close: Close price
            macd_histogram: MACD histogram value
        """
        ta_currency_dir = self.ta_dir / currency
        ta_currency_dir.mkdir(parents=True, exist_ok=True)
        
        data = {
            "Open_Time_ms": [1000000],
            "Close_Time_ms": [1003599999],
            "Close": [close],
            "RSI_14": [rsi],
            "EMA_12": [ema_12],
            "EMA_26": [ema_26],
            "EMA_200": [ema_200],
            "MACD": [100.0],
            "MACD_Signal": [50.0],
            "MACD_Histogram": [macd_histogram]
        }
        
        df = pd.DataFrame(data)
        ta_file = ta_currency_dir / f"{currency}_ta.csv"
        df.to_csv(ta_file, index=False)
    
    def _create_portfolio_file(self, currencies_data: dict):
        """
        Create a mock portfolio file.
        
        Args:
            currencies_data: Dict mapping currency to dict with balance, current_value_usdc, etc.
        """
        self.summarised_dir.mkdir(parents=True, exist_ok=True)
        
        rows = []
        for currency, data in currencies_data.items():
            rows.append({
                "currency": currency,
                "balance": data.get("balance", "0.00000000"),
                "current_rate_usdc": data.get("current_rate_usdc", "0.00000000"),
                "current_value_usdc": data.get("current_value_usdc", "0.00000000"),
                "previous_rate_usdc": data.get("previous_rate_usdc", "0.00000000"),
                "percentage_change": data.get("percentage_change", "0.00"),
                "value_change_usdc": data.get("value_change_usdc", "0.00000000")
            })
        
        portfolio_file = self.summarised_dir / "portfolio.csv"
        with open(portfolio_file, "w", newline="", encoding="utf-8") as f:
            fieldnames = ["currency", "balance", "current_rate_usdc", "current_value_usdc",
                         "previous_rate_usdc", "percentage_change", "value_change_usdc"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    
    def test_read_ta_signals_success(self):
        """Test that TA signals are correctly read from ta directory."""
        self._create_ta_file("BTC", rsi=45.0, close=50000.0)
        
        rebalancer = RebalancePortfolio(self.cfg)
        ta_df = rebalancer.read_ta_signals("BTC")
        
        self.assertIsNotNone(ta_df)
        self.assertFalse(ta_df.empty)
        self.assertEqual(len(ta_df), 1)
        self.assertIn("RSI_14", ta_df.columns)
        self.assertEqual(ta_df.iloc[0]["RSI_14"], 45.0)
        self.assertEqual(ta_df.iloc[0]["Close"], 50000.0)
    
    def test_read_ta_signals_missing_file(self):
        """Test that missing TA files are handled gracefully."""
        rebalancer = RebalancePortfolio(self.cfg)
        ta_df = rebalancer.read_ta_signals("NONEXISTENT")
        
        self.assertIsNone(ta_df)
    
    def test_load_portfolio_success(self):
        """Test that portfolio is correctly loaded from summarised directory."""
        currencies_data = {
            "BTC": {"balance": "1.00000000", "current_value_usdc": "50000.00000000"},
            "ETH": {"balance": "10.00000000", "current_value_usdc": "30000.00000000"},
            "SOL": {"balance": "100.00000000", "current_value_usdc": "10000.00000000"}
        }
        self._create_portfolio_file(currencies_data)
        
        rebalancer = RebalancePortfolio(self.cfg)
        portfolio_df = rebalancer.load_portfolio()
        
        self.assertIsNotNone(portfolio_df)
        self.assertEqual(len(portfolio_df), 3)
        self.assertIn("currency", portfolio_df.columns)
        self.assertIn("current_value_usdc", portfolio_df.columns)
    
    def test_load_portfolio_missing_file(self):
        """Test that missing portfolio file is handled gracefully."""
        rebalancer = RebalancePortfolio(self.cfg)
        portfolio_df = rebalancer.load_portfolio()
        
        self.assertIsNone(portfolio_df)
    
    def test_score_ta_indicators_bullish(self):
        """Test scoring mechanism for bullish indicators."""
        # Create bullish scenario:
        # - RSI < 30 (oversold): +2
        # - EMA_12 > EMA_26: +1
        # - Close > EMA_200: +1
        # - MACD_Histogram > 0: +1
        # Total: +5
        self._create_ta_file("BTC", rsi=25.0, ema_12=50000.0, ema_26=49000.0,
                           ema_200=48000.0, close=51000.0, macd_histogram=100.0)
        
        rebalancer = RebalancePortfolio(self.cfg)
        ta_df = rebalancer.read_ta_signals("BTC")
        score = rebalancer.score_ta_indicators(ta_df)
        
        self.assertEqual(score, 5)
    
    def test_score_ta_indicators_bearish(self):
        """Test scoring mechanism for bearish indicators."""
        # Create bearish scenario:
        # - RSI > 70 (overbought): -2
        # - EMA_12 < EMA_26: -1
        # - Close < EMA_200: -1
        # - MACD_Histogram < 0: -1
        # Total: -5
        self._create_ta_file("BTC", rsi=75.0, ema_12=49000.0, ema_26=50000.0,
                           ema_200=52000.0, close=48000.0, macd_histogram=-100.0)
        
        rebalancer = RebalancePortfolio(self.cfg)
        ta_df = rebalancer.read_ta_signals("BTC")
        score = rebalancer.score_ta_indicators(ta_df)
        
        self.assertEqual(score, -5)
    
    def test_score_ta_indicators_neutral(self):
        """Test scoring mechanism for neutral indicators."""
        # Create neutral scenario (RSI=50, mixed signals)
        self._create_ta_file("BTC", rsi=50.0, ema_12=50000.0, ema_26=50000.0,
                           ema_200=50000.0, close=50000.0, macd_histogram=0.0)
        
        rebalancer = RebalancePortfolio(self.cfg)
        ta_df = rebalancer.read_ta_signals("BTC")
        score = rebalancer.score_ta_indicators(ta_df)
        
        self.assertEqual(score, 0)
    
    def test_trade_threshold_prevents_sell(self):
        """Test that currencies below TRADE_THRESHOLD are not marked for sell."""
        # Create bearish TA signal (should trigger SELL)
        self._create_ta_file("BTC", rsi=75.0, ema_12=49000.0, ema_26=50000.0,
                           ema_200=52000.0, close=48000.0, macd_histogram=-100.0)
        
        # Portfolio with value below threshold ($50 < $100 threshold)
        currencies_data = {
            "BTC": {"balance": "0.00100000", "current_value_usdc": "50.00000000"}
        }
        self._create_portfolio_file(currencies_data)
        
        rebalancer = RebalancePortfolio(self.cfg)
        recommendations = rebalancer.generate_recommendations()
        
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]["currency"], "BTC")
        self.assertEqual(recommendations[0]["action"], "HOLD")
        self.assertIn("below threshold", recommendations[0]["reason"])
    
    def test_trade_threshold_allows_sell(self):
        """Test that currencies above TRADE_THRESHOLD can be sold."""
        # Create bearish TA signal
        self._create_ta_file("BTC", rsi=75.0, ema_12=49000.0, ema_26=50000.0,
                           ema_200=52000.0, close=48000.0, macd_histogram=-100.0)
        
        # Portfolio with value above threshold ($500 > $100 threshold)
        currencies_data = {
            "BTC": {"balance": "0.01000000", "current_value_usdc": "500.00000000"}
        }
        self._create_portfolio_file(currencies_data)
        
        rebalancer = RebalancePortfolio(self.cfg)
        recommendations = rebalancer.generate_recommendations()
        
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]["currency"], "BTC")
        self.assertEqual(recommendations[0]["action"], "SELL")
    
    def test_highest_score_gets_buy(self):
        """Test that currency with highest score gets BUY recommendation."""
        # Create TA files with different scores
        # BTC: bullish (score +5)
        self._create_ta_file("BTC", rsi=25.0, ema_12=50000.0, ema_26=49000.0,
                           ema_200=48000.0, close=51000.0, macd_histogram=100.0)
        # ETH: moderately bullish (score +2)
        self._create_ta_file("ETH", rsi=40.0, ema_12=3000.0, ema_26=2900.0,
                           ema_200=2800.0, close=3100.0, macd_histogram=50.0)
        # SOL: slightly bullish (score +1)
        self._create_ta_file("SOL", rsi=50.0, ema_12=100.0, ema_26=95.0,
                           ema_200=90.0, close=105.0, macd_histogram=-10.0)
        
        currencies_data = {
            "BTC": {"balance": "1.00000000", "current_value_usdc": "50000.00000000"},
            "ETH": {"balance": "10.00000000", "current_value_usdc": "30000.00000000"},
            "SOL": {"balance": "100.00000000", "current_value_usdc": "10000.00000000"}
        }
        self._create_portfolio_file(currencies_data)
        
        rebalancer = RebalancePortfolio(self.cfg)
        recommendations = rebalancer.generate_recommendations()
        
        # Find BUY recommendation
        buy_recs = [r for r in recommendations if r["action"] == "BUY"]
        self.assertEqual(len(buy_recs), 1)
        self.assertEqual(buy_recs[0]["currency"], "BTC")
        
        # Other positive currencies should be HOLD
        eth_rec = [r for r in recommendations if r["currency"] == "ETH"][0]
        sol_rec = [r for r in recommendations if r["currency"] == "SOL"][0]
        self.assertEqual(eth_rec["action"], "HOLD")
        self.assertEqual(sol_rec["action"], "HOLD")
    
    def test_tied_scores_first_in_list_chosen(self):
        """Test that when scores are tied, first currency in list is chosen for BUY."""
        # Create TA files with same positive score for all
        for currency in ["BTC", "ETH", "SOL"]:
            self._create_ta_file(currency, rsi=40.0, ema_12=50000.0, ema_26=49000.0,
                               ema_200=48000.0, close=51000.0, macd_histogram=100.0)
        
        currencies_data = {
            "BTC": {"balance": "1.00000000", "current_value_usdc": "50000.00000000"},
            "ETH": {"balance": "10.00000000", "current_value_usdc": "30000.00000000"},
            "SOL": {"balance": "100.00000000", "current_value_usdc": "10000.00000000"}
        }
        self._create_portfolio_file(currencies_data)
        
        rebalancer = RebalancePortfolio(self.cfg)
        recommendations = rebalancer.generate_recommendations()
        
        # First in alphabetical order should get BUY
        buy_recs = [r for r in recommendations if r["action"] == "BUY"]
        self.assertEqual(len(buy_recs), 1)
        self.assertEqual(buy_recs[0]["currency"], "BTC")
    
    def test_output_file_created(self):
        """Test that output recommendations are saved to rebalance.csv."""
        # Create minimal test data
        self._create_ta_file("BTC", rsi=50.0)
        currencies_data = {
            "BTC": {"balance": "1.00000000", "current_value_usdc": "50000.00000000"}
        }
        self._create_portfolio_file(currencies_data)
        
        rebalancer = RebalancePortfolio(self.cfg)
        recommendations = rebalancer.generate_recommendations()
        success = rebalancer.save_recommendations(recommendations)
        
        self.assertTrue(success)
        
        # Verify file exists
        output_file = self.output_dir / "rebalance.csv"
        self.assertTrue(output_file.exists())
    
    def test_output_file_content(self):
        """Test that output file contains expected recommendations."""
        # Create test data with known outcome
        self._create_ta_file("BTC", rsi=25.0, ema_12=50000.0, ema_26=49000.0,
                           ema_200=48000.0, close=51000.0, macd_histogram=100.0)
        currencies_data = {
            "BTC": {"balance": "1.00000000", "current_value_usdc": "50000.00000000"}
        }
        self._create_portfolio_file(currencies_data)
        
        rebalancer = RebalancePortfolio(self.cfg)
        recommendations = rebalancer.generate_recommendations()
        rebalancer.save_recommendations(recommendations)
        
        # Read and verify output
        output_file = self.output_dir / "rebalance.csv"
        with open(output_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["currency"], "BTC")
        self.assertEqual(rows[0]["action"], "BUY")
        self.assertEqual(rows[0]["score"], "5")
    
    def test_empty_portfolio(self):
        """Test handling of empty portfolio."""
        # Create empty portfolio file
        self._create_portfolio_file({})
        
        rebalancer = RebalancePortfolio(self.cfg)
        recommendations = rebalancer.generate_recommendations()
        
        self.assertEqual(len(recommendations), 0)
    
    def test_empty_ta_data(self):
        """Test handling when all currencies have no TA data."""
        currencies_data = {
            "BTC": {"balance": "1.00000000", "current_value_usdc": "50000.00000000"},
            "ETH": {"balance": "10.00000000", "current_value_usdc": "30000.00000000"}
        }
        self._create_portfolio_file(currencies_data)
        
        # Don't create any TA files
        rebalancer = RebalancePortfolio(self.cfg)
        recommendations = rebalancer.generate_recommendations()
        
        # Should return empty list since no TA data available
        self.assertEqual(len(recommendations), 0)
    
    def test_malformed_ta_data(self):
        """Test handling of malformed TA data."""
        # Create TA file with missing columns
        ta_currency_dir = self.ta_dir / "BTC"
        ta_currency_dir.mkdir(parents=True, exist_ok=True)
        
        data = {"Close": [50000.0]}  # Missing required TA indicators
        df = pd.DataFrame(data)
        ta_file = ta_currency_dir / "BTC_ta.csv"
        df.to_csv(ta_file, index=False)
        
        currencies_data = {
            "BTC": {"balance": "1.00000000", "current_value_usdc": "50000.00000000"}
        }
        self._create_portfolio_file(currencies_data)
        
        rebalancer = RebalancePortfolio(self.cfg)
        ta_df = rebalancer.read_ta_signals("BTC")
        
        # Should still load the file
        self.assertIsNotNone(ta_df)
        
        # Score should handle missing columns gracefully
        score = rebalancer.score_ta_indicators(ta_df)
        self.assertEqual(score, 0)  # Missing indicators = no score
    
    def test_run_full_pipeline(self):
        """Test full pipeline execution."""
        # Create complete test data
        self._create_ta_file("BTC", rsi=25.0, ema_12=50000.0, ema_26=49000.0,
                           ema_200=48000.0, close=51000.0, macd_histogram=100.0)
        self._create_ta_file("ETH", rsi=75.0, ema_12=2900.0, ema_26=3000.0,
                           ema_200=3200.0, close=2800.0, macd_histogram=-50.0)
        
        currencies_data = {
            "BTC": {"balance": "1.00000000", "current_value_usdc": "50000.00000000"},
            "ETH": {"balance": "10.00000000", "current_value_usdc": "500.00000000"}
        }
        self._create_portfolio_file(currencies_data)
        
        rebalancer = RebalancePortfolio(self.cfg)
        success = rebalancer.run()
        
        self.assertTrue(success)
        
        # Verify output file exists and has correct content
        output_file = self.output_dir / "rebalance.csv"
        self.assertTrue(output_file.exists())
        
        with open(output_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 2)
        
        # BTC should be BUY (positive score)
        btc_rec = [r for r in rows if r["currency"] == "BTC"][0]
        self.assertEqual(btc_rec["action"], "BUY")
        
        # ETH should be SELL (negative score, above threshold)
        eth_rec = [r for r in rows if r["currency"] == "ETH"][0]
        self.assertEqual(eth_rec["action"], "SELL")
    
    def test_multiple_currencies_with_mixed_signals(self):
        """Test complex scenario with multiple currencies and mixed signals."""
        # BTC: strong buy signal
        self._create_ta_file("BTC", rsi=25.0, ema_12=50000.0, ema_26=49000.0,
                           ema_200=48000.0, close=51000.0, macd_histogram=100.0)
        # ETH: weak buy signal
        self._create_ta_file("ETH", rsi=45.0, ema_12=3000.0, ema_26=2950.0,
                           ema_200=2900.0, close=3100.0, macd_histogram=10.0)
        # SOL: sell signal but below threshold
        self._create_ta_file("SOL", rsi=75.0, ema_12=95.0, ema_26=100.0,
                           ema_200=105.0, close=90.0, macd_histogram=-50.0)
        
        currencies_data = {
            "BTC": {"balance": "1.00000000", "current_value_usdc": "50000.00000000"},
            "ETH": {"balance": "10.00000000", "current_value_usdc": "30000.00000000"},
            "SOL": {"balance": "5.00000000", "current_value_usdc": "50.00000000"}  # Below threshold
        }
        self._create_portfolio_file(currencies_data)
        
        rebalancer = RebalancePortfolio(self.cfg)
        recommendations = rebalancer.generate_recommendations()
        
        self.assertEqual(len(recommendations), 3)
        
        # BTC should get BUY (highest score)
        btc_rec = [r for r in recommendations if r["currency"] == "BTC"][0]
        self.assertEqual(btc_rec["action"], "BUY")
        
        # ETH should be HOLD (positive but not highest)
        eth_rec = [r for r in recommendations if r["currency"] == "ETH"][0]
        self.assertEqual(eth_rec["action"], "HOLD")
        
        # SOL should be HOLD (negative but below threshold)
        sol_rec = [r for r in recommendations if r["currency"] == "SOL"][0]
        self.assertEqual(sol_rec["action"], "HOLD")
        self.assertIn("below threshold", sol_rec["reason"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
Tester för TechnicalAnalysis-modulen.

Dessa tester validerar att alla tekniska indikatorer beräknas korrekt.
"""
import unittest
import tempfile
import shutil
from pathlib import Path
import pandas as pd
import sys
import os

# Lägg till projektets rotmapp till path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hunk2.src.technical_analysis import TechnicalAnalysis
from hunk2.src.config import Config


class TestTechnicalAnalysis(unittest.TestCase):
    """Tester för TechnicalAnalysis-klassen."""

    def setUp(self):
        """Skapa temporär testmiljö."""
        self.test_dir = tempfile.mkdtemp()
        self.data_root = Path(self.test_dir)
        self.history_dir = self.data_root / "history" / "BTC"
        self.history_dir.mkdir(parents=True, exist_ok=True)

        # Skapa mock-config
        self.cfg = Config(
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
            trade_threshold=0.02,
            take_profit_percentage=10.0,  # 10% take profit
            stop_loss_percentage=6.0,  # 6% stop loss
            allowed_quote_assets=["USDT"],
            raw_env={}
        )

        # Skapa testdata med syntetisk prisserie
        self._create_test_history_file()

    def tearDown(self):
        """Rensa temporär testmiljö."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_test_history_file(self):
        """Skapa en realistisk testhistorikfil med 300 datapunkter."""
        # Skapa syntetisk prisserie med trend och volatilitet
        import numpy as np
        
        n_points = 300
        base_price = 50000
        trend = np.linspace(0, 5000, n_points)  # Uppåtgående trend
        noise = np.random.normal(0, 500, n_points)  # Slumpmässig volatilitet
        prices = base_price + trend + noise
        
        data = {
            "Open_Time_ms": [1000000 + i * 3600000 for i in range(n_points)],
            "Open": prices,
            "High": prices * 1.01,
            "Low": prices * 0.99,
            "Close": prices,
            "Volume": [100 + i for i in range(n_points)],
            "Close_Time_ms": [1000000 + i * 3600000 + 3599999 for i in range(n_points)],
            "Quote_Asset_Volume": [5000000 + i * 1000 for i in range(n_points)],
            "Number_of_Trades": [1000 + i for i in range(n_points)],
            "Taker_Buy_Base_Asset_Volume": [50 + i * 0.5 for i in range(n_points)],
            "Taker_Buy_Quote_Asset_Volume": [2500000 + i * 500 for i in range(n_points)],
        }
        
        df = pd.DataFrame(data)
        csv_file = self.history_dir / "BTC_history.csv"
        df.to_csv(csv_file, index=False)

    def test_read_history_csv(self):
        """Testa att historikfil kan läsas korrekt."""
        ta = TechnicalAnalysis(self.cfg)
        df = ta._read_history_csv("BTC")
        
        self.assertIsNotNone(df)
        self.assertFalse(df.empty)
        self.assertEqual(len(df), 300)
        self.assertIn("Close", df.columns)

    def test_read_history_csv_missing_file(self):
        """Testa att läsning av saknad fil returnerar None."""
        ta = TechnicalAnalysis(self.cfg)
        df = ta._read_history_csv("NONEXISTENT")
        
        self.assertIsNone(df)

    def test_calculate_rsi(self):
        """Testa RSI-beräkning."""
        ta = TechnicalAnalysis(self.cfg)
        df = ta._read_history_csv("BTC")
        
        rsi = ta._calculate_rsi(df["Close"], period=14)
        
        # RSI ska vara mellan 0 och 100
        valid_rsi = rsi.dropna()
        self.assertTrue((valid_rsi >= 0).all())
        self.assertTrue((valid_rsi <= 100).all())
        
        # De första 14 värdena ska vara NaN (warming up period)
        self.assertTrue(pd.isna(rsi.iloc[0]))

    def test_calculate_ema(self):
        """Testa EMA-beräkning."""
        ta = TechnicalAnalysis(self.cfg)
        df = ta._read_history_csv("BTC")
        
        # Testa olika perioder
        for period in [12, 26, 200]:
            ema = ta._calculate_ema(df["Close"], period=period)
            
            # EMA ska ha samma längd som input
            self.assertEqual(len(ema), len(df))
            
            # EMA ska vara numeriska värden
            self.assertFalse(ema.isna().all())

    def test_calculate_macd(self):
        """Testa MACD-beräkning."""
        ta = TechnicalAnalysis(self.cfg)
        df = ta._read_history_csv("BTC")
        
        macd_line, signal_line, histogram = ta._calculate_macd(df["Close"])
        
        # Alla tre komponenter ska ha samma längd
        self.assertEqual(len(macd_line), len(df))
        self.assertEqual(len(signal_line), len(df))
        self.assertEqual(len(histogram), len(df))
        
        # MACD histogram ska vara skillnaden mellan MACD och signal
        # (kontrollera för icke-NaN värden)
        valid_idx = ~macd_line.isna() & ~signal_line.isna()
        expected_histogram = macd_line[valid_idx] - signal_line[valid_idx]
        pd.testing.assert_series_equal(
            histogram[valid_idx], 
            expected_histogram,
            check_names=False
        )

    def test_calculate_indicators(self):
        """Testa att alla indikatorer beräknas."""
        ta = TechnicalAnalysis(self.cfg)
        result_df = ta.calculate_indicators("BTC")
        
        self.assertIsNotNone(result_df)
        self.assertFalse(result_df.empty)
        
        # Kontrollera att alla förväntade kolumner finns
        expected_columns = [
            "Close",
            "RSI_14",
            "EMA_12",
            "EMA_26", 
            "EMA_200",
            "MACD",
            "MACD_Signal",
            "MACD_Histogram"
        ]
        
        for col in expected_columns:
            self.assertIn(col, result_df.columns, f"Kolumn {col} saknas")

    def test_save_ta_results(self):
        """Testa att TA-resultat sparas korrekt."""
        ta = TechnicalAnalysis(self.cfg)
        result_df = ta.calculate_indicators("BTC")
        
        success = ta.save_ta_results("BTC", result_df)
        
        self.assertTrue(success)
        
        # Verifiera att filen skapades
        ta_file = self.data_root / "ta" / "BTC" / "BTC_ta.csv"
        self.assertTrue(ta_file.exists())
        
        # Verifiera att filen kan läsas och har rätt innehåll
        saved_df = pd.read_csv(ta_file)
        self.assertEqual(len(saved_df), len(result_df))

    def test_run_full_pipeline(self):
        """Testa fullständig körning av TA-pipeline."""
        ta = TechnicalAnalysis(self.cfg)
        success = ta.run()
        
        self.assertTrue(success)
        
        # Verifiera att TA-fil skapades
        ta_file = self.data_root / "ta" / "BTC" / "BTC_ta.csv"
        self.assertTrue(ta_file.exists())
        
        # Läs och verifiera innehållet
        df = pd.read_csv(ta_file)
        self.assertGreater(len(df), 0)
        self.assertIn("RSI_14", df.columns)
        self.assertIn("EMA_12", df.columns)
        self.assertIn("EMA_26", df.columns)
        self.assertIn("EMA_200", df.columns)
        self.assertIn("MACD", df.columns)

    def test_ema_200_with_insufficient_data(self):
        """Testa att EMA_200 hanteras korrekt även med färre än 200 datapunkter."""
        # Skapa ny config med bara 100 datapunkter
        short_history_dir = self.data_root / "history" / "ETH"
        short_history_dir.mkdir(parents=True, exist_ok=True)
        
        # Skapa kort historikfil
        import numpy as np
        n_points = 100
        prices = 3000 + np.linspace(0, 500, n_points)
        data = {
            "Open_Time_ms": [1000000 + i * 3600000 for i in range(n_points)],
            "Open": prices,
            "High": prices,
            "Low": prices,
            "Close": prices,
            "Volume": [100 for _ in range(n_points)],
            "Close_Time_ms": [1000000 + i * 3600000 + 3599999 for i in range(n_points)],
            "Quote_Asset_Volume": [5000000 for _ in range(n_points)],
            "Number_of_Trades": [1000 for _ in range(n_points)],
            "Taker_Buy_Base_Asset_Volume": [50 for _ in range(n_points)],
            "Taker_Buy_Quote_Asset_Volume": [2500000 for _ in range(n_points)],
        }
        df = pd.DataFrame(data)
        csv_file = short_history_dir / "ETH_history.csv"
        df.to_csv(csv_file, index=False)
        
        # Uppdatera config för ETH
        cfg_eth = Config(
            currencies=["ETH"],
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
            currency_history_nof_elements=100,
            trade_threshold=0.02,
            take_profit_percentage=10.0,  # 10% take profit
            stop_loss_percentage=6.0,  # 6% stop loss
            allowed_quote_assets=["USDT"],
            raw_env={}
        )
        
        ta = TechnicalAnalysis(cfg_eth)
        result_df = ta.calculate_indicators("ETH")
        
        self.assertIsNotNone(result_df)
        self.assertIn("EMA_200", result_df.columns)
        # EMA_200 ska beräknas även om det finns färre än 200 punkter


if __name__ == "__main__":
    unittest.main()

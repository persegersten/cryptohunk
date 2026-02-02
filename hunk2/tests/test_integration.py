#!/usr/bin/env python3
"""
Integration test för att verifiera att TA-modulen fungerar med riktig datastruktur.
"""
import tempfile
import shutil
from pathlib import Path
import pandas as pd
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from hunk2.src.technical_analysis import TechnicalAnalysis
from hunk2.src.config import Config


def test_integration():
    """Test full integration with realistic data."""
    test_dir = tempfile.mkdtemp()
    try:
        data_root = Path(test_dir)
        
        # Create test config
        cfg = Config(
            currencies=["BTC", "ETH"],
            binance_secret="test_secret",
            binance_key="test_key",
            binance_base_url="https://api.binance.com",
            binance_currency_history_endpoint="/api/v3/klines",
            binance_exchange_info_endpoint="/api/v3/exchangeInfo",
            binance_my_trades_endpoint="/api/v3/myTrades",
            binance_trading_url="https://api.binance.com/api/v3/order",
            dry_run=True,
            data_area_root_dir=str(data_root),
            currency_history_period="1h",
            currency_history_nof_elements=300,
            trade_threshold=0.02,
            allowed_quote_assets=["USDT"],
            raw_env={}
        )
        
        # Create sample history files
        for currency in cfg.currencies:
            history_dir = data_root / "history" / currency
            history_dir.mkdir(parents=True, exist_ok=True)
            
            # Create realistic test data
            import numpy as np
            n_points = 300
            base_price = 50000 if currency == "BTC" else 3000
            trend = np.linspace(0, base_price * 0.1, n_points)
            noise = np.random.normal(0, base_price * 0.01, n_points)
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
            csv_file = history_dir / f"{currency}_history.csv"
            df.to_csv(csv_file, index=False)
            print(f"✓ Created test data for {currency}")
        
        # Run TA
        ta = TechnicalAnalysis(cfg)
        success = ta.run()
        
        if not success:
            print("✗ TA run failed")
            return False
        
        print("✓ TA processing completed")
        
        # Verify output files
        for currency in cfg.currencies:
            ta_file = data_root / "ta" / currency / f"{currency}_ta.csv"
            if not ta_file.exists():
                print(f"✗ TA file not created for {currency}")
                return False
            
            # Read and validate content
            ta_df = pd.read_csv(ta_file)
            
            required_columns = [
                "Close", "RSI_14", "EMA_12", "EMA_26", "EMA_200",
                "MACD", "MACD_Signal", "MACD_Histogram"
            ]
            
            for col in required_columns:
                if col not in ta_df.columns:
                    print(f"✗ Missing column {col} in {currency}_ta.csv")
                    return False
            
            print(f"✓ Verified TA output for {currency} ({len(ta_df)} rows, {len(ta_df.columns)} columns)")
            
            # Verify some values are not all NaN
            if ta_df["RSI_14"].dropna().empty:
                print(f"✗ All RSI values are NaN for {currency}")
                return False
            
            if ta_df["EMA_12"].dropna().empty:
                print(f"✗ All EMA_12 values are NaN for {currency}")
                return False
        
        print("\n✅ Integration test PASSED")
        return True
        
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    success = test_integration()
    sys.exit(0 if success else 1)

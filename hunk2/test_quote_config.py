#!/usr/bin/env python3
"""
Test the quote assets configuration feature.
"""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.config import Config
from src.assert_env import load_config_from_env, _parse_currencies


def test_parse_currencies():
    """Test the _parse_currencies function."""
    # Test normal case
    result = _parse_currencies("USDT,USDC,BUSD")
    assert result == ["USDT", "USDC", "BUSD"], f"Expected ['USDT', 'USDC', 'BUSD'], got {result}"
    
    # Test with spaces
    result = _parse_currencies("usdt, usdc , busd")
    assert result == ["USDT", "USDC", "BUSD"], f"Expected ['USDT', 'USDC', 'BUSD'], got {result}"
    
    # Test empty
    result = _parse_currencies("")
    assert result == [], f"Expected [], got {result}"
    
    print("✓ _parse_currencies tests passed")


def test_config_dataclass():
    """Test that Config dataclass has allowed_quote_assets field."""
    cfg = Config(
        currencies=["BTC", "ETH"],
        binance_secret="test_secret",
        binance_key="test_key",
        binance_base_url="https://api.binance.com",
        binance_currency_history_endpoint="/api/v3/klines",
        binance_exchange_info_endpoint="/api/v3/exchangeInfo",
        binance_my_trades_endpoint="/api/v3/myTrades",
        binance_trading_url="https://trading.binance.com",
        dry_run=True,
        data_area_root_dir="/tmp/test",
        currency_history_period="1h",
        currency_history_nof_elements=100,
        trade_threshold=0.01,
        raw_env={},
        allowed_quote_assets=["USDT", "USDC"],
    )
    
    assert cfg.allowed_quote_assets == ["USDT", "USDC"], \
        f"Expected ['USDT', 'USDC'], got {cfg.allowed_quote_assets}"
    
    print("✓ Config dataclass test passed")


def test_load_config_with_quote_assets():
    """Test loading config with QUOTE_ASSETS env var."""
    # Set up minimal environment
    os.environ["CURRENCIES"] = "BTC,ETH"
    os.environ["BINANCE_SECRET"] = "test_secret"
    os.environ["BINANCE_KEY"] = "test_key"
    os.environ["BINANCE_TRADING_URL"] = "https://trading.binance.com"
    os.environ["DATA_AREA_ROOT_DIR"] = "/tmp/test"
    os.environ["CURRENCY_HISTORY_PERIOD"] = "1h"
    os.environ["CURRENCY_HISTORY_NOF_ELEMENTS"] = "100"
    os.environ["TRADE_THRESHOLD"] = "0.01"
    os.environ["QUOTE_ASSETS"] = "USDT,BUSD,EUR"
    
    cfg = load_config_from_env()
    
    assert cfg.allowed_quote_assets == ["USDT", "BUSD", "EUR"], \
        f"Expected ['USDT', 'BUSD', 'EUR'], got {cfg.allowed_quote_assets}"
    
    print("✓ load_config_from_env with QUOTE_ASSETS test passed")


def test_default_quote_assets():
    """Test that QUOTE_ASSETS defaults to USDT,USDC."""
    # Set up minimal environment without QUOTE_ASSETS
    os.environ["CURRENCIES"] = "BTC,ETH"
    os.environ["BINANCE_SECRET"] = "test_secret"
    os.environ["BINANCE_KEY"] = "test_key"
    os.environ["BINANCE_TRADING_URL"] = "https://trading.binance.com"
    os.environ["DATA_AREA_ROOT_DIR"] = "/tmp/test"
    os.environ["CURRENCY_HISTORY_PERIOD"] = "1h"
    os.environ["CURRENCY_HISTORY_NOF_ELEMENTS"] = "100"
    os.environ["TRADE_THRESHOLD"] = "0.01"
    
    # Remove QUOTE_ASSETS if it exists
    if "QUOTE_ASSETS" in os.environ:
        del os.environ["QUOTE_ASSETS"]
    
    cfg = load_config_from_env()
    
    assert cfg.allowed_quote_assets == ["USDT", "USDC"], \
        f"Expected default ['USDT', 'USDC'], got {cfg.allowed_quote_assets}"
    
    print("✓ Default QUOTE_ASSETS test passed")


if __name__ == "__main__":
    print("Running quote assets configuration tests...\n")
    
    try:
        test_parse_currencies()
        test_config_dataclass()
        test_load_config_with_quote_assets()
        test_default_quote_assets()
        
        print("\n✅ All tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

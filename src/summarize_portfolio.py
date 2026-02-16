#!/usr/bin/env python3
"""
SummarizePortfolio - Generate portfolio summary with current values and percentage changes.

This module:
1. Fetches current USDC exchange rates for currencies from Binance API
2. Analyzes trade history to find last purchase price for each currency
3. Calculates percentage change since last purchase
4. Calculates absolute value change in USDC: CurrentValue_USDC - (PreviousRate * Balance)
5. Handles missing currencies by marking them as 0
6. Saves the summary to CSV format at DATA_AREA_ROOT_DIR/summarised/portfolio.csv
"""
import logging
import json
import csv
import requests
from pathlib import Path
from typing import Optional

from .config import Config

log = logging.getLogger(__name__)


def fetch_current_usdc_rate(cfg: Config, currency: str) -> Optional[float]:
    """
    Fetch the current exchange rate for a given currency in USDC from Binance API.
    
    Args:
        cfg: Configuration object with Binance API details
        currency: The currency symbol (e.g., "BNB", "ETH")
    
    Returns:
        Current exchange rate as float, or None if unavailable
    """
    if currency.upper() == "USDC":
        return 1.0
    
    try:
        symbol = f"{currency.upper()}USDC"
        base_url = cfg.binance_base_url.rstrip("/")
        url = f"{base_url}/api/v3/ticker/price"
        params = {"symbol": symbol}
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        price = float(data.get("price", 0))
        
        if price > 0:
            log.info(f"Fetched current rate for {currency}: {price} USDC")
            return price
        else:
            log.warning(f"Invalid price for {currency}: {price}")
            return None
            
    except requests.exceptions.RequestException as e:
        log.warning(f"Failed to fetch current rate for {currency}: {e}")
        return None
    except (ValueError, KeyError) as e:
        log.warning(f"Failed to parse price for {currency}: {e}")
        return None


def fetch_previous_usdc_value(cfg: Config, currency: str) -> Optional[float]:
    """
    Analyze trade history to extract the USDC value at the time of last purchase.
    
    Args:
        cfg: Configuration object with data directory path
        currency: The currency symbol (e.g., "BNB", "ETH")
    
    Returns:
        Last purchase price in USDC as float, or None if no purchase found
    """
    if currency.upper() == "USDC":
        return 1.0
    
    try:
        trades_file = Path(cfg.data_area_root_dir) / "trades" / "trades.json"
        
        if not trades_file.exists():
            log.warning(f"Trades file not found: {trades_file}")
            return None
        
        with open(trades_file, "r", encoding="utf-8") as f:
            trades = json.load(f)
        
        if not isinstance(trades, list):
            log.warning(f"Invalid trades data format")
            return None
        
        # Filter trades for this currency where it was bought (isBuyer=true)
        # Check for both USDC and USDT as quote assets
        # Use exact symbol matching to avoid false positives
        relevant_trades = []
        currency_usdc = f"{currency.upper()}USDC"
        currency_usdt = f"{currency.upper()}USDT"
        
        for trade in trades:
            symbol = trade.get("symbol", "")
            is_buyer = trade.get("isBuyer", False)
            
            # Check if this trade involves our currency with exact symbol match
            if (symbol == currency_usdc or symbol == currency_usdt) and is_buyer:
                relevant_trades.append(trade)
        
        if not relevant_trades:
            log.info(f"No purchase trades found for {currency}")
            return None
        
        # Sort by time (most recent first)
        relevant_trades.sort(key=lambda x: x.get("time", 0), reverse=True)
        last_trade = relevant_trades[0]
        
        # Extract price from the last purchase
        price = float(last_trade.get("price", 0))
        
        if price > 0:
            log.info(f"Last purchase price for {currency}: {price} USDC/USDT")
            return price
        else:
            log.warning(f"Invalid last purchase price for {currency}: {price}")
            return None
            
    except FileNotFoundError:
        log.warning(f"Trades file not found for {currency}")
        return None
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse trades JSON: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error fetching previous value for {currency}: {e}")
        return None


def summarize_portfolio(cfg: Config) -> None:
    """
    Generate portfolio summary with current values and percentage changes.
    
    This function:
    1. Iterates over currencies in Config
    2. Fetches current and previous values
    3. Calculates percentage change
    4. Calculates absolute value change in USDC
    5. Handles missing currencies by marking as 0
    6. Saves to CSV at DATA_AREA_ROOT_DIR/summarised/portfolio.csv
    
    Args:
        cfg: Configuration object
    """
    log.info("=== Startar SummarizePortfolio ===")
    
    # Ensure summarised directory exists
    summarised_dir = Path(cfg.data_area_root_dir) / "summarised"
    summarised_dir.mkdir(parents=True, exist_ok=True)
    
    # Load portfolio data
    portfolio_file = Path(cfg.data_area_root_dir) / "portfolio" / "portfolio.json"
    portfolio_balances = {}
    
    try:
        if portfolio_file.exists():
            with open(portfolio_file, "r", encoding="utf-8") as f:
                portfolio_data = json.load(f)
                portfolio_balances = portfolio_data.get("balances", {})
                log.info(f"Loaded portfolio with {len(portfolio_balances)} assets")
        else:
            log.warning(f"Portfolio file not found: {portfolio_file}")
    except Exception as e:
        log.error(f"Failed to load portfolio: {e}")
    
    # Prepare summary data
    summary_rows = []
    
    # Process all currencies including quote assets (e.g., USDC, USDT)
    # Use set to avoid duplicates if a currency appears in both lists
    all_currencies = list(set(list(cfg.currencies) + list(cfg.allowed_quote_assets)))
    
    for currency in all_currencies:
        currency_upper = currency.upper()
        log.info(f"Processing {currency_upper}...")
        
        # Get balance from portfolio
        balance_info = portfolio_balances.get(currency_upper)
        if balance_info:
            try:
                balance = float(balance_info.get("total", 0))
            except (ValueError, TypeError):
                balance = None
        else:
            balance = None
        
        # Fetch current rate
        current_rate = fetch_current_usdc_rate(cfg, currency_upper)
        
        # Fetch previous rate
        previous_rate = fetch_previous_usdc_value(cfg, currency_upper)
        
        # Calculate current value
        if balance is not None and current_rate is not None:
            current_value = balance * current_rate
        else:
            current_value = None
        
        # Calculate percentage change
        if current_rate is not None and previous_rate is not None and previous_rate > 0:
            percentage_change = ((current_rate - previous_rate) / previous_rate) * 100
        else:
            percentage_change = None
        
        # Calculate value change in USDC: CurrentValue_USDC - (PreviousRate * Balance)
        if current_value is not None and previous_rate is not None and balance is not None:
            value_change_usdc = current_value - (previous_rate * balance)
        else:
            value_change_usdc = None
        
        # Format values for CSV
        row = {
            "currency": currency_upper,
            "balance": f"{balance:.8f}" if balance is not None else "0.00000000",
            "current_rate_usdc": f"{current_rate:.8f}" if current_rate is not None else "0.00000000",
            "current_value_usdc": f"{current_value:.8f}" if current_value is not None else "0.00000000",
            "previous_rate_usdc": f"{previous_rate:.8f}" if previous_rate is not None else "0.00000000",
            "value_change_usdc": f"{value_change_usdc:.8f}" if value_change_usdc is not None else "0.00000000",
            "percentage_change": f"{percentage_change:.2f}" if percentage_change is not None else "0.00"
        }
        
        summary_rows.append(row)
        log.info(f"{currency_upper}: balance={row['balance']}, current_rate={row['current_rate_usdc']}, "
                 f"current_value={row['current_value_usdc']}, value_change={row['value_change_usdc']}, "
                 f"previous_rate={row['previous_rate_usdc']}, change={row['percentage_change']}%")
    
    # Write to CSV
    csv_file = summarised_dir / "portfolio.csv"
    try:
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            if summary_rows:
                fieldnames = ["currency", "balance", "current_rate_usdc", "current_value_usdc", 
                             "previous_rate_usdc", "percentage_change", "value_change_usdc"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(summary_rows)
                log.info(f"Portfolio summary saved to: {csv_file}")
            else:
                log.warning("No summary data to write")
    except Exception as e:
        log.error(f"Failed to write CSV: {e}")
        raise
    
    log.info("=== SummarizePortfolio avslutad ===")


# Module-level convenience function
def summarize_portfolio_main(cfg: Config) -> None:
    """
    Main entry point for portfolio summarization.
    Called from main.py after data validation.
    """
    try:
        summarize_portfolio(cfg)
    except Exception as e:
        log.error(f"Portfolio summarization failed: {e}")
        raise

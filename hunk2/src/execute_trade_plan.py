#!/usr/bin/env python3
"""
ExecuteTradePlan - Execute trades from trade plan against Binance.

This module:
1. Reads trade plan from DATA_AREA_ROOT_DIR/output/rebalance/trade_plan.csv
2. Validates exchange info from BINANCE_BASE_URL/BINANCE_EXCHANGE_INFO_ENDPOINT
3. If DRY_RUN is true: logs trades without executing them
4. If DRY_RUN is false: uses CCXTBroker to place buy/sell orders on Binance
"""
import logging
import csv
from pathlib import Path
from typing import List, Dict, Optional
import ccxt

from .config import Config

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class CCXTBroker:
    """CCXT-based broker for executing trades on Binance."""
    
    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://api.binance.com"):
        """
        Initialize CCXT broker for Binance.
        
        Args:
            api_key: Binance API key
            api_secret: Binance API secret
            base_url: Binance base URL (default: https://api.binance.com)
        """
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'adjustForTimeDifference': True,
            'options': {
                'defaultType': 'spot'
            }
        })
        
        # Set custom base URL if different from default
        if base_url and base_url != "https://api.binance.com":
            self.exchange.urls['api'] = base_url
    
    def fetch_exchange_info(self) -> dict:
        """
        Fetch exchange information from Binance.
        
        Returns:
            Exchange info dictionary
        """
        try:
            return self.exchange.fetch_markets()
        except Exception as e:
            log.error(f"Failed to fetch exchange info: {e}")
            raise
    
    def fetch_price(self, symbol: str) -> float:
        """
        Fetch current price for a symbol.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDC')
        
        Returns:
            Current price
        
        Note:
            Price priority order: last > close > bid > ask
            - 'last': Most recent trade price (preferred for market orders)
            - 'close': Last candle close price (used if no recent trade)
            - 'bid': Current highest buy order (fallback)
            - 'ask': Current lowest sell order (final fallback)
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker.get('last') or ticker.get('close') or ticker.get('bid') or ticker.get('ask')
        except Exception as e:
            log.error(f"Failed to fetch price for {symbol}: {e}")
            raise
    
    def market_buy(self, symbol: str, quote_amount: float) -> dict:
        """
        Execute a market buy order.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDC')
            quote_amount: Amount to spend in quote currency (e.g., USDC)
        
        Returns:
            Order result dictionary
        """
        try:
            # Calculate quantity based on current price
            price = self.fetch_price(symbol)
            quantity = quote_amount / price
            
            log.info(f"Placing market BUY: {symbol}, quote_amount={quote_amount}, qty={quantity:.8f}, price={price}")
            order = self.exchange.create_market_buy_order(symbol, quantity)
            log.info(f"Market BUY order placed successfully: {order.get('id', 'N/A')}")
            return order
        except Exception as e:
            log.error(f"Failed to execute market buy for {symbol}: {e}")
            raise
    
    def market_sell(self, symbol: str, base_quantity: float) -> dict:
        """
        Execute a market sell order.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDC')
            base_quantity: Amount to sell in base currency (e.g., BTC)
        
        Returns:
            Order result dictionary
        """
        try:
            price = self.fetch_price(symbol)
            log.info(f"Placing market SELL: {symbol}, qty={base_quantity:.8f}, price={price}")
            order = self.exchange.create_market_sell_order(symbol, base_quantity)
            log.info(f"Market SELL order placed successfully: {order.get('id', 'N/A')}")
            return order
        except Exception as e:
            log.error(f"Failed to execute market sell for {symbol}: {e}")
            raise


class ExecuteTradePlan:
    """Execute trades from trade plan."""
    
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.data_root = Path(cfg.data_area_root_dir)
        self.output_root = self.data_root / "output" / "rebalance"
        self.broker = None
    
    def _init_broker(self) -> None:
        """Initialize CCXT broker if not in dry run mode."""
        if not self.cfg.dry_run and self.broker is None:
            log.info("Initializing CCXTBroker for live trading")
            self.broker = CCXTBroker(
                api_key=self.cfg.binance_key,
                api_secret=self.cfg.binance_secret,
                base_url=self.cfg.binance_base_url
            )
    
    def _validate_exchange_info(self) -> bool:
        """
        Validate exchange info from Binance.
        
        Returns:
            True if exchange info is valid, False otherwise
        """
        log.info(f"Validating exchange info from {self.cfg.binance_base_url}{self.cfg.binance_exchange_info_endpoint}")
        
        try:
            if self.cfg.dry_run:
                log.info("DRY_RUN mode: skipping exchange info validation")
                return True
            
            self._init_broker()
            exchange_info = self.broker.fetch_exchange_info()
            
            if not exchange_info:
                log.error("Exchange info is empty")
                return False
            
            log.info(f"Exchange info validated successfully: {len(exchange_info)} markets available")
            return True
            
        except Exception as e:
            log.error(f"Failed to validate exchange info: {e}")
            return False
    
    def _read_trade_plan(self) -> Optional[List[Dict]]:
        """
        Read trade plan from CSV file.
        
        Returns:
            List of trade dictionaries or None if file not found
        """
        trade_plan_file = self.output_root / "trade_plan.csv"
        
        if not trade_plan_file.exists():
            log.error(f"Trade plan file not found: {trade_plan_file}")
            return None
        
        try:
            trades = []
            with open(trade_plan_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trades.append(row)
            
            log.info(f"Read trade plan with {len(trades)} trades from: {trade_plan_file}")
            return trades
            
        except Exception as e:
            log.error(f"Failed to read trade plan: {e}")
            return None
    
    def _execute_trade_dry_run(self, trade: Dict) -> None:
        """
        Log trade without executing (dry run mode).
        
        Args:
            trade: Trade dictionary with action, currency, amount, value_usdc
        """
        action = trade['action']
        currency = trade['currency']
        amount = trade['amount']
        value_usdc = trade['value_usdc']
        
        log.info(f"DRY_RUN: Would execute {action} {currency} - amount: {amount}, value: {value_usdc} USDC")
    
    def _execute_trade_live(self, trade: Dict) -> bool:
        """
        Execute trade using CCXTBroker.
        
        Args:
            trade: Trade dictionary with action, currency, amount, value_usdc
        
        Returns:
            True if successful, False otherwise
        
        Note:
            Currently assumes USDC as the quote currency for all trades.
            This is consistent with the trade_plan.csv format which uses value_usdc.
            If support for other quote currencies is needed (e.g., USDT), the trade_plan
            CSV format should be extended to include a 'quote_currency' column.
        """
        action = trade['action']
        currency = trade['currency']
        amount = trade['amount']
        value_usdc = float(trade['value_usdc'])
        
        # Construct symbol using USDC as quote currency
        # This matches the trade plan CSV format which uses 'value_usdc' column
        symbol = f"{currency}/USDC"
        
        try:
            if action == 'BUY':
                # For BUY, amount is 'ALL' meaning use all liquid funds
                log.info(f"Executing BUY: {currency} with {value_usdc} USDC")
                self.broker.market_buy(symbol, value_usdc)
                log.info(f"Successfully executed BUY: {currency}")
                return True
                
            elif action == 'SELL':
                # For SELL, amount is the base quantity to sell
                quantity = float(amount)
                log.info(f"Executing SELL: {currency} - quantity: {quantity}")
                self.broker.market_sell(symbol, quantity)
                log.info(f"Successfully executed SELL: {currency}")
                return True
            else:
                log.error(f"Unknown action: {action}")
                return False
                
        except Exception as e:
            log.error(f"Failed to execute {action} for {currency}: {e}")
            return False
    
    def execute_trades(self) -> bool:
        """
        Execute all trades from trade plan.
        
        Returns:
            True if all trades executed successfully, False otherwise
        """
        log.info("=== Starting trade execution ===")
        
        # Validate exchange info
        if not self._validate_exchange_info():
            log.error("Exchange info validation failed")
            return False
        
        # Read trade plan
        trades = self._read_trade_plan()
        if trades is None:
            log.error("Failed to read trade plan")
            return False
        
        if not trades:
            log.info("Trade plan is empty, no trades to execute")
            return True
        
        # Initialize broker if not in dry run mode
        if not self.cfg.dry_run:
            self._init_broker()
        
        # Execute trades
        success_count = 0
        failure_count = 0
        
        for i, trade in enumerate(trades, 1):
            log.info(f"Processing trade {i}/{len(trades)}")
            
            if self.cfg.dry_run:
                self._execute_trade_dry_run(trade)
                success_count += 1
            else:
                if self._execute_trade_live(trade):
                    success_count += 1
                else:
                    failure_count += 1
        
        log.info(f"Trade execution completed: {success_count} successful, {failure_count} failed")
        
        if failure_count > 0:
            log.error(f"{failure_count} trades failed")
            return False
        
        return True
    
    def run(self) -> bool:
        """
        Run the trade execution process.
        
        Returns:
            True on success, False on failure
        """
        log.info("=== Starting ExecuteTradePlan ===")
        
        try:
            success = self.execute_trades()
            
            if success:
                log.info("ExecuteTradePlan completed successfully")
            else:
                log.error("ExecuteTradePlan failed")
            
            return success
            
        except Exception as e:
            log.error(f"Unexpected error in ExecuteTradePlan: {e}")
            return False


def execute_trade_plan_main(cfg: Config) -> None:
    """
    Main entry point for trade execution.
    Called from main.py when --execute-trades flag is set.
    Raises SystemExit(1) on failure.
    """
    executor = ExecuteTradePlan(cfg)
    success = executor.run()
    if not success:
        log.error("ExecuteTradePlan failed")
        raise SystemExit(1)


if __name__ == "__main__":
    """
    Run from command line. Gets env via assert_env_and_report() for Config.
    Example:
      python3 hunk2/src/execute_trade_plan.py
    """
    from .assert_env import assert_env_and_report
    
    try:
        cfg = assert_env_and_report()
    except Exception as e:
        log.error(f"Config could not be loaded: {e}")
        raise SystemExit(2)
    
    success = ExecuteTradePlan(cfg).run()
    raise SystemExit(0 if success else 1)

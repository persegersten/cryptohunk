#!/usr/bin/env python3
"""
CreateTradePlan - Generate a trading plan based on portfolio and rebalance recommendations.

This module:
1. Reads current portfolio from DATA_AREA_ROOT_DIR/summarised/portfolio.csv
2. Reads rebalance recommendations from DATA_AREA_ROOT_DIR/output/rebalance/recommendations.csv
3. Generates trade plan based on rules:
   - Process SELL recommendations first: if value in USDC > TRADE_THRESHOLD, sell entire holding
   - Calculate liquid funds after SELLs
   - Process BUY recommendations: if liquid funds > TRADE_THRESHOLD, execute ONE BUY with all funds
4. Saves trade plan to DATA_AREA_ROOT_DIR/output/rebalance/trade_plan.csv
"""
import logging
import csv
from pathlib import Path
from typing import List, Dict, Optional
import pandas as pd

from .config import Config

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class CreateTradePlan:
    """Generate trading plan based on portfolio and rebalance recommendations."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.data_root = Path(cfg.data_area_root_dir)
        self.summarised_root = self.data_root / "summarised"
        self.output_root = self.data_root / "output" / "rebalance"

    def _ensure_dir(self, path: Path) -> None:
        """Create directory if it doesn't exist."""
        path.mkdir(parents=True, exist_ok=True)

    def _read_portfolio_summary(self) -> Optional[pd.DataFrame]:
        """
        Read portfolio summary.
        
        Returns:
            DataFrame with portfolio summary or None if not found
        """
        portfolio_file = self.summarised_root / "portfolio.csv"
        
        if not portfolio_file.exists():
            log.error(f"Portfolio summary file not found: {portfolio_file}")
            return None
        
        try:
            df = pd.read_csv(portfolio_file)
            if df.empty:
                log.warning("Portfolio summary file is empty")
                return None
            return df
        except Exception as e:
            log.error(f"Failed to read portfolio summary: {e}")
            return None

    def _read_recommendations(self) -> Optional[pd.DataFrame]:
        """
        Read rebalance recommendations.
        
        Returns:
            DataFrame with recommendations or None if not found
        """
        recommendations_file = self.output_root / "recommendations.csv"
        
        if not recommendations_file.exists():
            log.error(f"Recommendations file not found: {recommendations_file}")
            return None
        
        try:
            df = pd.read_csv(recommendations_file)
            if df.empty:
                log.info("Recommendations file is empty")
                return pd.DataFrame(columns=['currency', 'percentage_change', 'ta_score', 'signal'])
            return df
        except Exception as e:
            log.error(f"Failed to read recommendations: {e}")
            return None

    def _get_liquid_funds(self, portfolio_df: pd.DataFrame) -> float:
        """
        Get current liquid funds (USDC balance) from portfolio.
        
        Args:
            portfolio_df: Portfolio DataFrame
        
        Returns:
            Liquid funds in USDC
        """
        # USDC row should have currency='USDC' and current_value_usdc represents the balance
        usdc_row = portfolio_df[portfolio_df['currency'] == 'USDC']
        if usdc_row.empty:
            log.warning("USDC not found in portfolio, assuming 0 liquid funds")
            return 0.0
        
        try:
            liquid_funds = float(usdc_row.iloc[0]['current_value_usdc'])
            log.info(f"Current liquid funds: {liquid_funds:.2f} USDC")
            return liquid_funds
        except (ValueError, KeyError) as e:
            log.error(f"Error parsing USDC balance: {e}")
            return 0.0

    def generate_trade_plan(self) -> List[Dict]:
        """
        Generate trade plan based on portfolio and recommendations.
        
        Returns:
            List of trade plan dictionaries
        """
        log.info("=== Generating trade plan ===")
        
        # Read inputs
        portfolio_df = self._read_portfolio_summary()
        if portfolio_df is None:
            log.error("Cannot proceed without portfolio summary")
            return []
        
        recommendations_df = self._read_recommendations()
        if recommendations_df is None:
            log.error("Cannot proceed without recommendations")
            return []
        
        trade_plan = []
        liquid_funds = self._get_liquid_funds(portfolio_df)
        
        # Process SELL recommendations first
        sell_recommendations = recommendations_df[recommendations_df['signal'] == 'SELL']
        
        for _, rec in sell_recommendations.iterrows():
            currency = rec['currency']
            
            # Get current value from portfolio
            portfolio_row = portfolio_df[portfolio_df['currency'] == currency]
            if portfolio_row.empty:
                log.warning(f"Currency {currency} not found in portfolio, skipping SELL")
                continue
            
            try:
                current_value_usdc = float(portfolio_row.iloc[0]['current_value_usdc'])
                balance = float(portfolio_row.iloc[0]['balance'])
            except (ValueError, KeyError) as e:
                log.error(f"Error parsing portfolio data for {currency}: {e}")
                continue
            
            # Check if value exceeds threshold
            if current_value_usdc > self.cfg.trade_threshold:
                # Sell entire holding
                trade = {
                    'action': 'SELL',
                    'currency': currency,
                    'amount': f"{balance:.8f}",
                    'value_usdc': f"{current_value_usdc:.2f}"
                }
                trade_plan.append(trade)
                liquid_funds += current_value_usdc
                log.info(f"SELL: {currency} for {current_value_usdc:.2f} USDC (amount: {balance:.8f})")
            else:
                log.info(f"SELL {currency} skipped: value {current_value_usdc:.2f} USDC <= threshold {self.cfg.trade_threshold}")
        
        log.info(f"Liquid funds after SELLs: {liquid_funds:.2f} USDC")
        
        # Process BUY recommendations - only if liquid funds > threshold
        if liquid_funds > self.cfg.trade_threshold:
            buy_recommendations = recommendations_df[recommendations_df['signal'] == 'BUY']
            
            if not buy_recommendations.empty:
                # Take first BUY recommendation (already sorted by priority in recommendations.csv)
                first_buy = buy_recommendations.iloc[0]
                currency = first_buy['currency']
                
                trade = {
                    'action': 'BUY',
                    'currency': currency,
                    'amount': 'ALL',  # Buy for all liquid funds
                    'value_usdc': f"{liquid_funds:.2f}"
                }
                trade_plan.append(trade)
                log.info(f"BUY: {currency} with all liquid funds ({liquid_funds:.2f} USDC)")
            else:
                log.info("No BUY recommendations available")
        else:
            log.info(f"BUY skipped: liquid funds {liquid_funds:.2f} USDC <= threshold {self.cfg.trade_threshold}")
        
        log.info(f"Generated trade plan with {len(trade_plan)} trades")
        return trade_plan

    def save_trade_plan(self, trade_plan: List[Dict]) -> bool:
        """
        Save trade plan to CSV file.
        
        Args:
            trade_plan: List of trade dictionaries
        
        Returns:
            True on success, False on failure
        """
        self._ensure_dir(self.output_root)
        output_file = self.output_root / "trade_plan.csv"
        
        try:
            fieldnames = ['action', 'currency', 'amount', 'value_usdc']
            
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                if trade_plan:
                    writer.writerows(trade_plan)
            
            log.info(f"Saved trade plan with {len(trade_plan)} trades to: {output_file}")
            return True
            
        except Exception as e:
            log.error(f"Failed to save trade plan: {e}")
            return False

    def run(self) -> bool:
        """
        Run the trade plan generation process.
        
        Returns:
            True on success, False on failure
        """
        log.info("=== Starting CreateTradePlan ===")
        
        try:
            # Generate trade plan
            trade_plan = self.generate_trade_plan()
            
            # Save to file
            success = self.save_trade_plan(trade_plan)
            
            if success:
                log.info(f"CreateTradePlan completed: {len(trade_plan)} trades in plan")
            else:
                log.error("CreateTradePlan failed to save trade plan")
            
            return success
            
        except Exception as e:
            log.error(f"Unexpected error in CreateTradePlan: {e}")
            return False


def create_trade_plan_main(cfg: Config) -> None:
    """
    Main entry point for trade plan generation.
    Called from main.py when --create-trade-plan flag is set.
    Raises SystemExit(1) on failure.
    """
    log.info("=== Starting CreateTradePlan ===")
    creator = CreateTradePlan(cfg)
    success = creator.run()
    if not success:
        log.error("CreateTradePlan failed")
        raise SystemExit(1)


if __name__ == "__main__":
    """
    Run from command line. Gets env via assert_env_and_report() for Config.
    Example:
      python3 hunk2/src/create_trade_plan.py
    """
    from .assert_env import assert_env_and_report
    
    try:
        cfg = assert_env_and_report()
    except Exception as e:
        log.error(f"Config could not be loaded: {e}")
        raise SystemExit(2)

    success = CreateTradePlan(cfg).run()
    raise SystemExit(0 if success else 1)

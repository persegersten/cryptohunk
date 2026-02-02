#!/usr/bin/env python3
"""
RebalancePortfolio - Generate buy/sell recommendations based on TA signals and holdings.

This module:
1. Reads TA signals from DATA_AREA_ROOT_DIR/ta/<currency>/<currency>_ta.csv
2. Reads portfolio summary from DATA_AREA_ROOT_DIR/summarised/portfolio.csv
3. Calculates TA scores based on:
   - RSI_14 < 30: +1, RSI_14 > 70: -1
   - EMA_12 > EMA_26: +1, EMA_12 < EMA_26: -1
   - MACD > MACD_Signal: +1, MACD < MACD_Signal: -1
   - Close > EMA_200: +1, Close < EMA_200: -1
4. Generates signals: score >= 1 = BUY, score <= -1 = SELL
5. Applies override rules:
   - If holdings < TRADE_THRESHOLD and profit > 10%: SELL (overrides TA)
   - If holdings < TRADE_THRESHOLD: no SELL
6. Selects max 1 BUY (highest score, first if tie), multiple SELL allowed
7. Saves recommendations to DATA_AREA_ROOT_DIR/output/rebalance/recommendations.csv
"""
import logging
import csv
from pathlib import Path
from typing import Optional, List, Dict
import pandas as pd

from .config import Config

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class RebalancePortfolio:
    """Generate portfolio rebalancing recommendations based on TA signals."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.data_root = Path(cfg.data_area_root_dir)
        self.ta_root = self.data_root / "ta"
        self.summarised_root = self.data_root / "summarised"
        self.output_root = self.data_root / "output" / "rebalance"

    def _ensure_dir(self, path: Path) -> None:
        """Create directory if it doesn't exist."""
        path.mkdir(parents=True, exist_ok=True)

    def _read_ta_data(self, currency: str) -> Optional[pd.DataFrame]:
        """
        Read TA data for a currency.
        
        Args:
            currency: Currency symbol (e.g., "BTC", "ETH")
        
        Returns:
            DataFrame with TA indicators or None if not found
        """
        ta_file = self.ta_root / currency / f"{currency}_ta.csv"
        
        if not ta_file.exists():
            log.warning(f"TA file not found for {currency}: {ta_file}")
            return None
        
        try:
            df = pd.read_csv(ta_file)
            if df.empty:
                log.warning(f"TA file is empty for {currency}")
                return None
            return df
        except Exception as e:
            log.error(f"Failed to read TA file for {currency}: {e}")
            return None

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

    def _calculate_ta_score(self, last_row: pd.Series) -> int:
        """
        Calculate TA score for the last data point.
        
        Scoring rules:
        - RSI_14 < 30: +1
        - RSI_14 > 70: -1
        - EMA_12 > EMA_26: +1
        - EMA_12 < EMA_26: -1
        - MACD > MACD_Signal: +1
        - MACD < MACD_Signal: -1
        - Close > EMA_200: +1
        - Close < EMA_200: -1
        
        Args:
            last_row: Last row of TA data
        
        Returns:
            TA score (integer)
        """
        score = 0
        
        try:
            # RSI signals
            rsi = last_row.get("RSI_14")
            if pd.notna(rsi):
                if rsi < 30:
                    score += 1
                elif rsi > 70:
                    score -= 1
            
            # EMA crossover signals
            ema_12 = last_row.get("EMA_12")
            ema_26 = last_row.get("EMA_26")
            if pd.notna(ema_12) and pd.notna(ema_26):
                if ema_12 > ema_26:
                    score += 1
                elif ema_12 < ema_26:
                    score -= 1
            
            # MACD signals
            macd = last_row.get("MACD")
            macd_signal = last_row.get("MACD_Signal")
            if pd.notna(macd) and pd.notna(macd_signal):
                if macd > macd_signal:
                    score += 1
                elif macd < macd_signal:
                    score -= 1
            
            # Price vs EMA_200 signals
            close = last_row.get("Close")
            ema_200 = last_row.get("EMA_200")
            if pd.notna(close) and pd.notna(ema_200):
                if close > ema_200:
                    score += 1
                elif close < ema_200:
                    score -= 1
        
        except Exception as e:
            log.error(f"Error calculating TA score: {e}")
        
        return score

    def _generate_signal(self, currency: str, ta_score: int, 
                        current_value_usdc: float, percentage_change: float) -> str:
        """
        Generate BUY/SELL/HOLD signal based on TA score and portfolio rules.
        
        Rules:
        1. If score >= 1: BUY signal
        2. If score <= -1: SELL signal
        3. Override: If holdings < TRADE_THRESHOLD and profit > 10%: SELL (trumps TA)
        4. If holdings < TRADE_THRESHOLD: no SELL
        
        Args:
            currency: Currency symbol
            ta_score: TA score
            current_value_usdc: Current value in USDC
            percentage_change: Percentage change since last purchase
        
        Returns:
            Signal: "BUY", "SELL", or "HOLD"
        """
        trade_threshold = self.cfg.trade_threshold
        
        # Step 3: If holdings < TRADE_THRESHOLD, no SELL
        if current_value_usdc < trade_threshold:
            # Step 2 override: If profit > 10%, force SELL even with small holdings
            if percentage_change > 10.0:
                log.info(f"{currency}: Holdings < TRADE_THRESHOLD but profit > 10% -> SELL (override)")
                return "SELL"
            
            # Don't sell if holdings are too small
            if ta_score <= -1:
                log.info(f"{currency}: Holdings < TRADE_THRESHOLD -> no SELL (despite TA score {ta_score})")
                return "HOLD"
        
        # Step 1: Normal TA-based signals
        if ta_score >= 1:
            return "BUY"
        elif ta_score <= -1:
            return "SELL"
        else:
            return "HOLD"

    def generate_recommendations(self) -> List[Dict]:
        """
        Generate buy/sell recommendations for all currencies.
        
        Returns:
            List of recommendation dictionaries
        """
        log.info("=== Generating rebalancing recommendations ===")
        
        # Read portfolio summary
        portfolio_df = self._read_portfolio_summary()
        if portfolio_df is None:
            log.error("Cannot proceed without portfolio summary")
            return []
        
        recommendations = []
        
        # Process each currency
        for currency in self.cfg.currencies:
            currency_upper = currency.upper()
            log.info(f"Processing {currency_upper}...")
            
            # Get TA data
            ta_df = self._read_ta_data(currency_upper)
            if ta_df is None or ta_df.empty:
                log.warning(f"Skipping {currency_upper} - no TA data")
                continue
            
            # Get last row for TA score calculation
            last_row = ta_df.iloc[-1]
            ta_score = self._calculate_ta_score(last_row)
            
            # Get portfolio info
            portfolio_row = portfolio_df[portfolio_df['currency'] == currency_upper]
            if portfolio_row.empty:
                log.warning(f"Currency {currency_upper} not found in portfolio summary")
                continue
            
            portfolio_row = portfolio_row.iloc[0]
            
            try:
                current_value_usdc = float(portfolio_row['current_value_usdc'])
                percentage_change = float(portfolio_row['percentage_change'])
            except (ValueError, KeyError) as e:
                log.error(f"Error parsing portfolio data for {currency_upper}: {e}")
                continue
            
            # Generate signal
            signal = self._generate_signal(
                currency_upper, ta_score, current_value_usdc, percentage_change
            )
            
            # Create recommendation
            recommendation = {
                'currency': currency_upper,
                'ta_score': ta_score,
                'current_value_usdc': f"{current_value_usdc:.8f}",
                'percentage_change': f"{percentage_change:.2f}",
                'signal': signal
            }
            
            recommendations.append(recommendation)
            log.info(f"{currency_upper}: TA score={ta_score}, value={current_value_usdc:.2f} USDC, "
                    f"change={percentage_change:.2f}%, signal={signal}")
        
        return recommendations

    def _select_final_recommendations(self, recommendations: List[Dict]) -> List[Dict]:
        """
        Select final recommendations according to rules:
        - Max 1 BUY (highest TA score, first if tie)
        - Multiple SELL allowed
        
        Args:
            recommendations: List of all recommendations
        
        Returns:
            Filtered list of recommendations
        """
        buy_recommendations = [r for r in recommendations if r['signal'] == 'BUY']
        sell_recommendations = [r for r in recommendations if r['signal'] == 'SELL']
        
        final_recommendations = []
        
        # Select max 1 BUY (highest score, first if tie)
        if buy_recommendations:
            # Sort by TA score (descending), then keep original order for ties
            buy_recommendations.sort(key=lambda x: x['ta_score'], reverse=True)
            selected_buy = buy_recommendations[0]
            final_recommendations.append(selected_buy)
            log.info(f"Selected BUY: {selected_buy['currency']} with TA score {selected_buy['ta_score']}")
        
        # Add all SELL recommendations
        final_recommendations.extend(sell_recommendations)
        for sell_rec in sell_recommendations:
            log.info(f"Selected SELL: {sell_rec['currency']} with TA score {sell_rec['ta_score']}")
        
        return final_recommendations

    def save_recommendations(self, recommendations: List[Dict]) -> bool:
        """
        Save recommendations to CSV file.
        
        Args:
            recommendations: List of recommendation dictionaries
        
        Returns:
            True on success, False on failure
        """
        self._ensure_dir(self.output_root)
        output_file = self.output_root / "recommendations.csv"
        
        try:
            if not recommendations:
                log.warning("No recommendations to save")
                # Create empty file with headers
                with open(output_file, 'w', newline='', encoding='utf-8') as f:
                    fieldnames = ['currency', 'ta_score', 'current_value_usdc', 
                                'percentage_change', 'signal']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                log.info(f"Created empty recommendations file: {output_file}")
                return True
            
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                fieldnames = ['currency', 'ta_score', 'current_value_usdc', 
                            'percentage_change', 'signal']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(recommendations)
            
            log.info(f"Saved {len(recommendations)} recommendations to: {output_file}")
            return True
            
        except Exception as e:
            log.error(f"Failed to save recommendations: {e}")
            return False

    def run(self) -> bool:
        """
        Run the rebalancing process.
        
        Returns:
            True on success, False on failure
        """
        log.info("=== Starting RebalancePortfolio ===")
        
        try:
            # Generate all recommendations
            all_recommendations = self.generate_recommendations()
            
            if not all_recommendations:
                log.warning("No recommendations generated")
                return self.save_recommendations([])
            
            # Select final recommendations (max 1 BUY, multiple SELL)
            final_recommendations = self._select_final_recommendations(all_recommendations)
            
            # Save to file
            success = self.save_recommendations(final_recommendations)
            
            if success:
                log.info(f"RebalancePortfolio completed: {len(final_recommendations)} recommendations")
            else:
                log.error("RebalancePortfolio failed to save recommendations")
            
            return success
            
        except Exception as e:
            log.error(f"Unexpected error in RebalancePortfolio: {e}")
            return False


def rebalance_portfolio_main(cfg: Config) -> None:
    """
    Main entry point for portfolio rebalancing.
    Called from main.py when --rebalance-portfolio flag is set.
    Raises SystemExit(1) on failure.
    """
    log.info("=== Starting RebalancePortfolio ===")
    rebalancer = RebalancePortfolio(cfg)
    success = rebalancer.run()
    if not success:
        log.error("RebalancePortfolio failed")
        raise SystemExit(1)


if __name__ == "__main__":
    """
    Run from command line. Gets env via assert_env_and_report() for Config.
    Example:
      python3 hunk2/src/rebalance_portfolio.py
    """
    from .assert_env import assert_env_and_report
    
    try:
        cfg = assert_env_and_report()
    except Exception as e:
        log.error(f"Config could not be loaded: {e}")
        raise SystemExit(2)

    success = RebalancePortfolio(cfg).run()
    raise SystemExit(0 if success else 1)

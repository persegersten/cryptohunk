#!/usr/bin/env python3
"""
RebalancePortfolio - Generate rebalance recommendations based on TA signals and portfolio state.

This module:
1. Reads TA signals from DATA_AREA_ROOT_DIR/ta/<currency>/<currency>_ta.csv
2. Loads portfolio from DATA_AREA_ROOT_DIR/summarised/portfolio.csv
3. Scores each currency based on TA indicators (RSI, EMA, MACD)
4. Generates BUY/SELL/HOLD recommendations
5. Ensures currencies below TRADE_THRESHOLD are not sold
6. Selects the currency with highest score for single BUY recommendation
7. Saves recommendations to DATA_AREA_ROOT_DIR/output/rebalance/rebalance.csv
"""
import logging
import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd

from .config import Config

log = logging.getLogger(__name__)


class RebalancePortfolio:
    """
    Generates portfolio rebalancing recommendations based on technical analysis signals.
    """
    
    def __init__(self, cfg: Config):
        """
        Initialize RebalancePortfolio with configuration.
        
        Args:
            cfg: Configuration object with currencies and data paths
        """
        self.cfg = cfg
        self.data_root = Path(cfg.data_area_root_dir)
        self.ta_dir = self.data_root / "ta"
        self.summarised_dir = self.data_root / "summarised"
        self.output_dir = self.data_root / "output" / "rebalance"
    
    def read_ta_signals(self, currency: str) -> Optional[pd.DataFrame]:
        """
        Read TA signals for a given currency.
        
        Args:
            currency: Currency symbol (e.g., "BTC", "ETH")
        
        Returns:
            DataFrame with TA indicators, or None if file doesn't exist
        """
        ta_file = self.ta_dir / currency / f"{currency}_ta.csv"
        
        if not ta_file.exists():
            log.warning(f"TA file not found: {ta_file}")
            return None
        
        try:
            df = pd.read_csv(ta_file)
            log.info(f"Loaded TA signals for {currency}: {len(df)} rows")
            return df
        except Exception as e:
            log.error(f"Failed to read TA file for {currency}: {e}")
            return None
    
    def load_portfolio(self) -> Optional[pd.DataFrame]:
        """
        Load portfolio data from summarised directory.
        
        Returns:
            DataFrame with portfolio data, or None if file doesn't exist
        """
        portfolio_file = self.summarised_dir / "portfolio.csv"
        
        if not portfolio_file.exists():
            log.warning(f"Portfolio file not found: {portfolio_file}")
            return None
        
        try:
            df = pd.read_csv(portfolio_file)
            log.info(f"Loaded portfolio: {len(df)} currencies")
            return df
        except Exception as e:
            log.error(f"Failed to read portfolio file: {e}")
            return None
    
    def score_ta_indicators(self, ta_df: pd.DataFrame) -> int:
        """
        Score TA indicators for a currency.
        
        Scoring rules:
        - RSI < 30: +2 points (oversold, bullish)
        - RSI > 70: -2 points (overbought, bearish)
        - EMA_12 > EMA_26: +1 point (bullish crossover)
        - EMA_12 < EMA_26: -1 point (bearish crossover)
        - Close > EMA_200: +1 point (above long-term trend)
        - Close < EMA_200: -1 point (below long-term trend)
        - MACD_Histogram > 0: +1 point (bullish momentum)
        - MACD_Histogram < 0: -1 point (bearish momentum)
        
        Args:
            ta_df: DataFrame with TA indicators
        
        Returns:
            Integer score (positive = bullish, negative = bearish)
        """
        if ta_df is None or ta_df.empty:
            return 0
        
        # Use the most recent data point
        latest = ta_df.iloc[-1]
        score = 0
        
        # RSI scoring
        if pd.notna(latest.get("RSI_14")):
            rsi = latest["RSI_14"]
            if rsi < 30:
                score += 2
            elif rsi > 70:
                score -= 2
        
        # EMA crossover scoring
        if pd.notna(latest.get("EMA_12")) and pd.notna(latest.get("EMA_26")):
            if latest["EMA_12"] > latest["EMA_26"]:
                score += 1
            elif latest["EMA_12"] < latest["EMA_26"]:
                score -= 1
        
        # EMA_200 trend scoring
        if pd.notna(latest.get("Close")) and pd.notna(latest.get("EMA_200")):
            if latest["Close"] > latest["EMA_200"]:
                score += 1
            elif latest["Close"] < latest["EMA_200"]:
                score -= 1
        
        # MACD histogram scoring
        if pd.notna(latest.get("MACD_Histogram")):
            if latest["MACD_Histogram"] > 0:
                score += 1
            elif latest["MACD_Histogram"] < 0:
                score -= 1
        
        return score
    
    def generate_recommendations(self) -> List[Dict[str, str]]:
        """
        Generate rebalance recommendations for all currencies.
        
        Returns:
            List of recommendation dictionaries with keys: currency, action, score, reason
        """
        portfolio_df = self.load_portfolio()
        
        if portfolio_df is None or portfolio_df.empty:
            log.warning("No portfolio data available")
            return []
        
        recommendations = []
        scores = {}
        
        # Score each currency
        for _, row in portfolio_df.iterrows():
            currency = row["currency"]
            current_value = float(row.get("current_value_usdc", 0))
            
            # Read TA signals
            ta_df = self.read_ta_signals(currency)
            
            if ta_df is None:
                log.warning(f"No TA data for {currency}, skipping")
                continue
            
            # Calculate score
            score = self.score_ta_indicators(ta_df)
            scores[currency] = score
            
            # Determine action based on score and threshold
            if score < 0 and current_value > self.cfg.trade_threshold:
                # Only sell if above trade threshold
                action = "SELL"
                reason = f"Negative score ({score}), value above threshold"
            elif score < 0 and current_value <= self.cfg.trade_threshold:
                # Don't sell if below threshold
                action = "HOLD"
                reason = f"Negative score ({score}), but value below threshold {self.cfg.trade_threshold}"
            elif score == 0:
                action = "HOLD"
                reason = "Neutral score"
            else:
                # Positive score - candidate for BUY (will be resolved later)
                action = "BUY"
                reason = f"Positive score ({score})"
            
            recommendations.append({
                "currency": currency,
                "action": action,
                "score": str(score),
                "reason": reason
            })
        
        # Only one BUY allowed - select highest score
        buy_candidates = [r for r in recommendations if r["action"] == "BUY"]
        
        if buy_candidates:
            # Sort by score (descending), then by currency name (ascending) for tie-breaking
            buy_candidates.sort(key=lambda x: (-int(x["score"]), x["currency"]))
            best_buy = buy_candidates[0]
            
            # Change all other BUYs to HOLD
            for rec in recommendations:
                if rec["action"] == "BUY" and rec["currency"] != best_buy["currency"]:
                    rec["action"] = "HOLD"
                    rec["reason"] = f"Positive score ({rec['score']}), but {best_buy['currency']} has higher score"
            
            log.info(f"Selected {best_buy['currency']} for BUY with score {best_buy['score']}")
        
        return recommendations
    
    def save_recommendations(self, recommendations: List[Dict[str, str]]) -> bool:
        """
        Save recommendations to CSV file.
        
        Args:
            recommendations: List of recommendation dictionaries
        
        Returns:
            True if successful, False otherwise
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_file = self.output_dir / "rebalance.csv"
        
        try:
            with open(output_file, "w", newline="", encoding="utf-8") as f:
                if recommendations:
                    fieldnames = ["currency", "action", "score", "reason"]
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(recommendations)
                    log.info(f"Saved {len(recommendations)} recommendations to {output_file}")
                else:
                    log.warning("No recommendations to save")
            return True
        except Exception as e:
            log.error(f"Failed to save recommendations: {e}")
            return False
    
    def run(self) -> bool:
        """
        Run the full rebalance portfolio pipeline.
        
        Returns:
            True if successful, False otherwise
        """
        log.info("=== Starting RebalancePortfolio ===")
        
        try:
            recommendations = self.generate_recommendations()
            
            if not recommendations:
                log.warning("No recommendations generated")
                # Still save empty file for consistency
                self.save_recommendations([])
                return True
            
            success = self.save_recommendations(recommendations)
            
            log.info("=== RebalancePortfolio completed ===")
            return success
        except Exception as e:
            log.error(f"RebalancePortfolio failed: {e}")
            return False


def rebalance_portfolio_main(cfg: Config) -> bool:
    """
    Main entry point for portfolio rebalancing.
    
    Args:
        cfg: Configuration object
    
    Returns:
        True if successful, False otherwise
    """
    rebalancer = RebalancePortfolio(cfg)
    return rebalancer.run()

import logging
import pandas as pd
from pathlib import Path
from typing import Dict, Any
from .config import Config

logger = logging.getLogger(__name__)

class RebalancePortfolio:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.data_dir = Path(cfg.data_area_root_dir)
        self.ta_dir = self.data_dir / "ta"
        self.output_dir = self.data_dir / "output" / "rebalance"
        self.portfolio_file = self.data_dir / "summarised" / "portfolio.csv"

    def _load_ta_for_currency(self, currency: str) -> pd.DataFrame:
        ta_file = self.ta_dir / currency / f"{currency}_ta.csv"
        if not ta_file.exists():
            logger.warning(f"TA file not found for {currency}: {ta_file}")
            return pd.DataFrame()
        return pd.read_csv(ta_file)

    def _load_portfolio(self) -> pd.DataFrame:
        if not self.portfolio_file.exists():
            logger.error(f"Portfolio file not found: {self.portfolio_file}")
            return pd.DataFrame()
        return pd.read_csv(self.portfolio_file)

    def _calculate_score(self, ta_row: Dict[str, Any]) -> int:
        score = 0
        if ta_row.get("RSI_14", 0) < 30:
            score += 1
        if ta_row.get("RSI_14", 0) > 70:
            score -= 1
        if ta_row.get("EMA_12", 0) > ta_row.get("EMA_26", 0):
            score += 1
        if ta_row.get("EMA_12", 0) < ta_row.get("EMA_26", 0):
            score -= 1
        if ta_row.get("MACD", 0) > ta_row.get("MACD_Signal", 0):
            score += 1
        if ta_row.get("MACD", 0) < ta_row.get("MACD_Signal", 0):
            score -= 1
        if ta_row.get("Close", 0) > ta_row.get("EMA_200", 0):
            score += 1
        if ta_row.get("Close", 0) < ta_row.get("EMA_200", 0):
            score -= 1
        return score

    def generate_recommendations(self):
        logger.info("Generating rebalancing recommendations...")

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Load portfolio data
        portfolio = self._load_portfolio()
        if portfolio.empty:
            logger.error("Portfolio data is empty. Aborting rebalancing.")
            return

        recommendations = []

        # Process each currency
        for currency in self.cfg.currencies:
            logger.info(f"Processing currency: {currency}")
            
            ta_data = self._load_ta_for_currency(currency)
            if ta_data.empty:
                continue

            # Get the latest TA data
            latest_ta = ta_data.iloc[-1]
            score = self._calculate_score(latest_ta)

            # Get portfolio balance and value
            portfolio_entry = portfolio.loc[portfolio["currency"] == currency.upper()]
            balance = float(portfolio_entry["balance"].values[0]) if not portfolio_entry.empty else 0
            current_value = float(portfolio_entry["current_value_usdc"].values[0]) if not portfolio_entry.empty else 0

            if score >= 1:
                recommendations.append({"currency": currency, "action": "BUY", "score": score})
            elif score <= -1:
                if current_value >= self.cfg.trade_threshold:
                    recommendations.append({"currency": currency, "action": "SELL", "score": score})

        # Save recommendations
        output_file = self.output_dir / "rebalance.csv"
        pd.DataFrame(recommendations).to_csv(output_file, index=False)
        logger.info(f"Recommendations saved to: {output_file}")

# Entry point for main.py

def rebalance_portfolio_main(cfg: Config):
    rebalancer = RebalancePortfolio(cfg)
    rebalancer.generate_recommendations()

#!/usr/bin/env python3
"""
RebalancePortfolio - Generate buy/sell recommendations based on TA signals and holdings.

This module:
1. Reads TA signals from DATA_AREA_ROOT_DIR/ta/<currency>/<currency>_ta.csv
2. Reads portfolio summary from DATA_AREA_ROOT_DIR/summarised/portfolio.csv
3. Calculates TA scores based on (TA strategy):
   - RSI_14 < 30: +1, RSI_14 > 70: -1
   - EMA_12 > EMA_26: +1, EMA_12 < EMA_26: -1
   - MACD > MACD_Signal: +1, MACD < MACD_Signal: -1
   - Close > EMA_200: +1, Close < EMA_200: -1
4. Alternatively (TA2 strategy, long-only trend-following pullback):
   - BUY when: Close > EMA_200, MACD > MACD_Signal, Close > EMA_21,
     RSI_14(t-1) <= 50 AND RSI_14(t) > 50, min(RSI_14 over last 8 candles before t) < 45
   - SELL when: MACD < MACD_Signal
5. Generates signals: score >= 1 = BUY, score <= -1 = SELL
6. Applies override rules:
   - Rule 1: If holdings < TRADE_THRESHOLD AND profit > take_profit_percentage: SELL (highest priority, overrides TA)
   - Rule 2: If holdings >= TRADE_THRESHOLD AND loss > stop_loss_percentage: SELL (high priority, overrides TA)
   - Rule 3: If holdings < TRADE_THRESHOLD: no SELL (even if TA says sell, unless Rule 1 applies)
7. TA is calculated for all configured currencies, even those without holdings (to enable BUY signals)
8. Multiple BUYs allowed, sorted by priority then absolute TA score (highest first)
9. Saves recommendations to DATA_AREA_ROOT_DIR/output/rebalance/recommendations.csv
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
            TA score (integer). Returns 0 if calculation fails.
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
            return 0
        
        return score

    def _calculate_ta2_signal(self, ta_df: pd.DataFrame) -> int:
        """
        Calculate TA2 signal (long-only trend-following pullback strategy).

        Entry (BUY) when all conditions are true on the latest candle t:
        - Close(t) > EMA_200(t)           -- trend filter
        - MACD(t) > MACD_Signal(t)        -- momentum confirmation
        - Close(t) > EMA_21(t)            -- price above short EMA
        - RSI_14(t-1) <= 50 AND RSI_14(t) > 50  -- RSI crosses up over 50
        - min(RSI_14(t-8)...RSI_14(t-1)) < 45   -- pullback/reset (excl. entry candle)
        - Optional: EMA_50(t) > EMA_200(t) if cfg.ta2_use_ema50_filter

        Exit (SELL): MACD(t) < MACD_Signal(t)

        Returns:
            1 (BUY), -1 (SELL), or 0 (HOLD)
        """
        LOOKBACK = 8

        if len(ta_df) < LOOKBACK + 1:
            log.debug("TA2: not enough rows for lookback (%d < %d)", len(ta_df), LOOKBACK + 1)
            return 0

        last = ta_df.iloc[-1]
        prev = ta_df.iloc[-2]

        # Helper to safely get a value
        def get(row, col):
            val = row.get(col)
            return None if val is None or pd.isna(val) else val

        macd = get(last, "MACD")
        macd_signal = get(last, "MACD_Signal")

        if macd is None or macd_signal is None:
            return 0

        # Exit rule: SELL when MACD < MACD_Signal
        if macd < macd_signal:
            return -1

        # Entry rules (all must be satisfied for BUY)
        close = get(last, "Close")
        ema_200 = get(last, "EMA_200")
        ema_21 = get(last, "EMA_21")
        rsi_t = get(last, "RSI_14")
        rsi_prev = get(prev, "RSI_14")

        if any(v is None for v in [close, ema_200, ema_21, rsi_t, rsi_prev]):
            return 0

        # 1. Trend filter
        if close <= ema_200:
            return 0

        # 2. Momentum confirmation (MACD > MACD_Signal; equal counts as HOLD)
        if macd <= macd_signal:
            return 0

        # 3. Price above short EMA
        if close <= ema_21:
            return 0

        # 4. RSI crosses up over 50
        if rsi_prev > 50 or rsi_t <= 50:
            return 0

        # 5. Pullback/reset: min(RSI_14(t-8)...RSI_14(t-1)) < 45
        #    Indices: t-8 to t-1 = ta_df["RSI_14"].iloc[-(LOOKBACK+1):-1]
        rsi_lookback = ta_df["RSI_14"].iloc[-(LOOKBACK + 1):-1]
        if rsi_lookback.isna().any() or rsi_lookback.min() >= 45:
            return 0

        # 6. Optional EMA50 trend-strength filter
        if self.cfg.ta2_use_ema50_filter:
            ema_50 = get(last, "EMA_50")
            if ema_50 is None or ema_50 <= ema_200:
                return 0

        return 1

    def _generate_signal(self, currency: str, ta_score: int, 
                        current_value_usdc: float, percentage_change: float) -> tuple:
        """
        Generate BUY/SELL/HOLD signal based on TA score and portfolio rules.
        
        Rules:
        - Rule 1: If holdings < TRADE_THRESHOLD AND profit > take_profit_percentage: SELL (highest priority, overrides TA)
        - Rule 2: If holdings >= TRADE_THRESHOLD AND loss > stop_loss_percentage: SELL (high priority, overrides TA)
        - Rule 3: If holdings < TRADE_THRESHOLD: no SELL (even if TA says sell, unless Rule 1 applies)
        - Otherwise: TA-based signals (score >= 1: BUY, score <= -1: SELL)
        
        Args:
            currency: Currency symbol
            ta_score: TA score
            current_value_usdc: Current value in USDC
            percentage_change: Percentage change since last purchase
        
        Returns:
            Tuple of (signal, priority) where:
            - signal: "BUY", "SELL", or "HOLD"
            - priority: 1 for Rule 1 (take profit with small holdings), 
                       2 for Rule 2 (stop loss), 3 for TA-based
        """
        trade_threshold = self.cfg.trade_threshold
        take_profit_pct = self.cfg.take_profit_percentage
        stop_loss_pct = self.cfg.stop_loss_percentage
        
        # Check if holdings are below threshold
        if current_value_usdc < trade_threshold:
            # Rule 1: If profit > take_profit_percentage, force SELL even with small holdings (highest priority)
            if percentage_change > take_profit_pct:
                log.info(f"{currency}: Holdings < TRADE_THRESHOLD but profit > {take_profit_pct}% -> SELL (Rule 1 priority)")
                return "SELL", 1
            
            # Rule 3: If holdings < TRADE_THRESHOLD, no SELL (even if TA says sell)
            if ta_score <= -1:
                log.info(f"{currency}: Holdings < TRADE_THRESHOLD -> no SELL (Rule 3, despite TA score {ta_score})")
                return "HOLD", 3
        else:
            # Rule 2: If holdings >= TRADE_THRESHOLD and loss > stop_loss_percentage, force SELL (high priority)
            if percentage_change < -stop_loss_pct:
                log.info(f"{currency}: Loss > {stop_loss_pct}% -> SELL (Rule 2 stop loss)")
                return "SELL", 2
        
        # TA-based signals for normal cases
        if ta_score >= 1:
            return "BUY", 3
        elif ta_score <= -1:
            return "SELL", 3
        else:
            return "HOLD", 3

    def generate_recommendations(self, use_ta2: bool = False) -> List[Dict]:
        """
        Generate buy/sell recommendations for all currencies.

        Args:
            use_ta2: If True, use TA2 (long-only trend-following pullback) strategy.
                     If False (default), use original TA score strategy.

        Returns:
            List of recommendation dictionaries
        """
        strategy_name = "TA2" if use_ta2 else "TA"
        log.info("=== Generating rebalancing recommendations (strategy: %s) ===", strategy_name)
        
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
            
            # Get portfolio info first
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
            
            # Get TA data (process even if no holdings to enable future BUY signals)
            ta_df = self._read_ta_data(currency_upper)
            if ta_df is None or ta_df.empty:
                log.warning(f"Skipping {currency_upper} - no TA data")
                continue
            
            # Get last row for TA score calculation
            last_row = ta_df.iloc[-1]
            if use_ta2:
                ta_score = self._calculate_ta2_signal(ta_df)
            else:
                ta_score = self._calculate_ta_score(last_row)
            
            # Generate signal with priority
            signal, priority = self._generate_signal(
                currency_upper, ta_score, current_value_usdc, percentage_change
            )
            
            # Create recommendation
            recommendation = {
                'currency': currency_upper,
                'percentage_change': f"{percentage_change:.2f}",
                'ta_score': ta_score,
                'signal': signal,
                'priority': priority,
                'abs_ta_score': abs(ta_score)
            }
            
            recommendations.append(recommendation)
            log.info(f"{currency_upper}: TA score={ta_score}, value={current_value_usdc:.2f} USDC, "
                    f"change={percentage_change:.2f}%, signal={signal}, priority={priority}")
        
        return recommendations

    def _select_final_recommendations(self, recommendations: List[Dict]) -> List[Dict]:
        """
        Select and sort final recommendations according to rules:
        - Multiple BUYs allowed
        - Multiple SELLs allowed
        - Sort by priority: Rule 1 (10% rule) > TA-based
        - Within same priority, sort by absolute TA score (highest first)
        - Within same absolute score, keep original order
        
        Args:
            recommendations: List of all recommendations
        
        Returns:
            Sorted list of recommendations (excluding HOLD)
        """
        # Filter out HOLD signals
        active_recommendations = [r for r in recommendations if r['signal'] != 'HOLD']
        
        if not active_recommendations:
            return []
        
        # Sort by:
        # 1. Priority (ascending: 1=Rule 1 comes first, 2=TA-based)
        # 2. Absolute TA score (descending: highest first)
        # 3. Keep stable sort for original order on ties
        active_recommendations.sort(
            key=lambda x: (x['priority'], -x['abs_ta_score'])
        )
        
        log.info(f"Selected {len(active_recommendations)} recommendations after filtering HOLD signals")
        for rec in active_recommendations:
            log.info(f"  {rec['signal']}: {rec['currency']} "
                    f"(priority={rec['priority']}, abs_ta_score={rec['abs_ta_score']}, ta_score={rec['ta_score']})")
        
        return active_recommendations

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
                    fieldnames = ['currency', 'percentage_change', 'ta_score', 'signal']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                log.info(f"Created empty recommendations file: {output_file}")
                return True
            
            # Remove internal fields before saving
            output_recommendations = []
            for rec in recommendations:
                output_rec = {
                    'currency': rec['currency'],
                    'percentage_change': rec['percentage_change'],
                    'ta_score': rec['ta_score'],
                    'signal': rec['signal']
                }
                output_recommendations.append(output_rec)
            
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                fieldnames = ['currency', 'percentage_change', 'ta_score', 'signal']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(output_recommendations)
            
            log.info(f"Saved {len(recommendations)} recommendations to: {output_file}")
            return True
            
        except Exception as e:
            log.error(f"Failed to save recommendations: {e}")
            return False

    def run(self, use_ta2: bool = False) -> bool:
        """
        Run the rebalancing process.

        Args:
            use_ta2: If True, use TA2 strategy for signal generation.

        Returns:
            True on success, False on failure
        """
        strategy_name = "TA2" if use_ta2 else "TA"
        log.info("=== Starting RebalancePortfolio (strategy: %s) ===", strategy_name)
        
        try:
            # Generate all recommendations
            all_recommendations = self.generate_recommendations(use_ta2=use_ta2)
            
            if not all_recommendations:
                log.warning("No recommendations generated")
                return self.save_recommendations([])
            
            # Select and sort final recommendations
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


def rebalance_portfolio_main(cfg: Config, use_ta2: bool = False) -> None:
    """
    Main entry point for portfolio rebalancing.
    Called from main.py when --rebalance-portfolio flag is set.
    Raises SystemExit(1) on failure.

    Args:
        cfg: Application configuration.
        use_ta2: If True, use TA2 strategy for signal generation.
    """
    rebalancer = RebalancePortfolio(cfg)
    success = rebalancer.run(use_ta2=use_ta2)
    if not success:
        log.error("RebalancePortfolio failed")
        raise SystemExit(1)


if __name__ == "__main__":
    """
    Run from command line. Gets env via assert_env_and_report() for Config.
    Example:
      python3 src/rebalance_portfolio.py
    """
    from .assert_env import assert_env_and_report
    
    try:
        cfg = assert_env_and_report()
    except Exception as e:
        log.error(f"Config could not be loaded: {e}")
        raise SystemExit(2)

    success = RebalancePortfolio(cfg).run()
    raise SystemExit(0 if success else 1)

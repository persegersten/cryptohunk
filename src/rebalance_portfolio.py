#!/usr/bin/env python3
"""
RebalancePortfolio - Generate buy/sell recommendations based on TA signals and holdings.

This module:
1. Reads TA signals from DATA_AREA_ROOT_DIR/ta/<currency>_ta.csv
2. Reads portfolio summary from DATA_AREA_ROOT_DIR/summarised/portfolio.csv
3. Calculates a continuous graded ta_score from multiple TA components:
   - Close vs EMA_200 (±2), Close vs EMA_21 (±1), EMA_21 vs EMA_50 (±1)
   - MACD vs MACD_Signal (±2), MACD bullish cross (+1)
   - RSI constructive zone (+1) or weak/overheated (-1)
   - Chase protection (-1 if price too extended above EMA_21)
   Score range approximately -8 to +8. Higher = more bullish.
4. Derives signal from graded score and explicit exit rule:
   - BUY when ta_score >= 5 (strong bullish setup, requires trend + momentum)
   - SELL when MACD < MACD_Signal (exit rule preserved from original strategy)
   - Optional: EMA_50 > EMA_200 filter blocks BUY if TA2_USE_EMA50_FILTER=true
   - HOLD otherwise
5. Applies override rules:
   - Rule 1: If profit > take_profit_percentage: SELL (highest priority, overrides TA)
   - Rule 2: If holdings >= TRADE_THRESHOLD AND loss > stop_loss_percentage: SELL (high priority, overrides TA)
   - Rule 3: If holdings < TRADE_THRESHOLD: no SELL (even if TA says sell, unless Rule 1 applies)
6. TA is calculated for all configured currencies, even those without holdings (to enable BUY signals)
7. Multiple BUYs allowed, sorted by priority then ta_score (highest first for BUY, most bearish first for SELL)
8. Saves recommendations to DATA_AREA_ROOT_DIR/output/rebalance/recommendations.csv
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

    # Minimum graded ta_score required for a BUY signal.
    # Requires at minimum Close > EMA_200 (+2) and MACD > Signal (+2) plus
    # at least one additional bullish component.
    _BUY_THRESHOLD = 5

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
        ta_file = self.ta_root / f"{currency}_ta.csv"
        
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

    def _calculate_ta_score(self, ta_df: pd.DataFrame) -> int:
        """
        Calculate continuous graded TA score for ranking.

        The score is built from multiple technical analysis components so that
        different currencies can be ranked against each other.  Higher positive
        score = stronger bullish setup; more negative = weaker / more bearish.

        Bullish components:
        - +2 if Close > EMA_200  (long-term trend)
        - +1 if Close > EMA_21   (short-term trend)
        - +1 if EMA_21 > EMA_50  (trend alignment)
        - +2 if MACD > MACD_Signal (momentum)
        - +1 if MACD bullish cross on current candle
        - +1 if RSI_14 in constructive zone (50–65)

        Bearish / weakening components:
        - -2 if Close <= EMA_200
        - -1 if Close <= EMA_21
        - -1 if EMA_21 <= EMA_50
        - -2 if MACD <= MACD_Signal
        - -1 if RSI_14 < 45  (weak)
        - -1 if RSI_14 > 70  (overheated)

        Chase protection:
        - -1 if Close is more than 3 % above EMA_21

        Range: approximately -8 to +8.

        Args:
            ta_df: DataFrame with TA indicators (at least 2 rows needed for
                   MACD-cross detection; returns 0 if fewer)

        Returns:
            Graded integer score.
        """
        if len(ta_df) < 2:
            return 0

        last = ta_df.iloc[-1]
        prev = ta_df.iloc[-2]

        def get(row, col):
            val = row.get(col)
            return None if val is None or pd.isna(val) else val

        score = 0

        close = get(last, "Close")
        ema_200 = get(last, "EMA_200")
        ema_21 = get(last, "EMA_21")
        ema_50 = get(last, "EMA_50")
        macd = get(last, "MACD")
        macd_signal = get(last, "MACD_Signal")
        macd_prev = get(prev, "MACD")
        macd_signal_prev = get(prev, "MACD_Signal")
        rsi = get(last, "RSI_14")

        # Close vs EMA_200 (long-term trend: ±2)
        if close is not None and ema_200 is not None:
            score += 2 if close > ema_200 else -2

        # Close vs EMA_21 (short-term trend: ±1)
        if close is not None and ema_21 is not None:
            score += 1 if close > ema_21 else -1

        # EMA_21 vs EMA_50 (trend alignment: ±1)
        if ema_21 is not None and ema_50 is not None:
            score += 1 if ema_21 > ema_50 else -1

        # MACD vs MACD_Signal (momentum: ±2)
        if macd is not None and macd_signal is not None:
            score += 2 if macd > macd_signal else -2

        # MACD bullish cross on current candle (+1)
        if all(v is not None for v in [macd, macd_signal, macd_prev, macd_signal_prev]):
            if macd_prev <= macd_signal_prev and macd > macd_signal:
                score += 1

        # RSI zone: 50-65 = constructive uptrend zone (+1),
        #           < 45 = weak momentum (-1), > 70 = overbought risk (-1)
        if rsi is not None:
            if 50 <= rsi <= 65:
                score += 1
            elif rsi < 45:
                score -= 1
            elif rsi > 70:
                score -= 1

        # Chase protection: penalty if price is too far above EMA_21
        if close is not None and ema_21 is not None and ema_21 > 0 and close > ema_21:
            stretch = close / ema_21 - 1
            if stretch > 0.03:
                score -= 1

        return score

    def _extract_signal_context(self, ta_df: pd.DataFrame) -> tuple:
        """
        Extract exit condition and EMA50 filter status from TA data.

        Args:
            ta_df: DataFrame with TA indicators (needs at least 1 row)

        Returns:
            Tuple of (macd_sell, ema50_blocks_buy):
            - macd_sell: True if MACD < MACD_Signal or Close < EMA_21 on the last candle
            - ema50_blocks_buy: True if EMA50 filter is enabled and blocks BUY
        """
        if ta_df.empty:
            return False, False

        last = ta_df.iloc[-1]

        def safe_get(col):
            val = last.get(col)
            return None if val is None or pd.isna(val) else val

        # Exit conditions: MACD bearish OR Close below EMA_21
        macd = safe_get("MACD")
        macd_signal = safe_get("MACD_Signal")
        macd_exit = macd is not None and macd_signal is not None and macd < macd_signal

        close = safe_get("Close")
        ema_21 = safe_get("EMA_21")
        ema21_exit = close is not None and ema_21 is not None and close < ema_21

        macd_sell = macd_exit or ema21_exit

        # Optional EMA50 trend-strength filter
        ema50_blocks_buy = False
        if self.cfg.ta2_use_ema50_filter:
            ema_50 = safe_get("EMA_50")
            ema_200 = safe_get("EMA_200")
            if ema_50 is None or ema_200 is None or ema_50 <= ema_200:
                ema50_blocks_buy = True

        return macd_sell, ema50_blocks_buy

    def _calculate_ta2_signal(self, ta_df: pd.DataFrame) -> int:
        """
        Calculate TA2 signal (long-only MACD-cross trend-following strategy).

        Entry (BUY) when all conditions are true on the latest candle t:
        - Close(t) > EMA_200(t)           -- trend filter
        - Close(t) > EMA_21(t)            -- price above short EMA
        - MACD(t-1) <= MACD_Signal(t-1)   -- previous candle not bullish
        - MACD(t) > MACD_Signal(t)        -- bullish MACD cross
        - Optional: EMA_50(t) > EMA_200(t) if cfg.ta2_use_ema50_filter

        Exit (SELL) when ANY of the following is true:
        - MACD(t) < MACD_Signal(t)        -- bearish MACD
        - Close(t) < EMA_21(t)            -- price below short EMA

        Returns:
            1 (BUY), -1 (SELL), or 0 (HOLD)
        """
        if len(ta_df) < 2:
            log.debug("TA2: not enough rows (need at least 2, have %d)", len(ta_df))
            return 0

        last = ta_df.iloc[-1]
        prev = ta_df.iloc[-2]

        # Helper to safely get a value
        def get(row, col):
            val = row.get(col)
            return None if val is None or pd.isna(val) else val

        macd = get(last, "MACD")
        macd_signal = get(last, "MACD_Signal")
        close = get(last, "Close")
        ema_21 = get(last, "EMA_21")

        # Exit rule: SELL when MACD < MACD_Signal OR Close < EMA_21
        macd_exit = macd is not None and macd_signal is not None and macd < macd_signal
        ema21_exit = close is not None and ema_21 is not None and close < ema_21

        if macd_exit or ema21_exit:
            return -1

        # Entry rules require MACD values to be present
        if macd is None or macd_signal is None:
            return 0

        # Entry rules (all must be satisfied for BUY)
        ema_200 = get(last, "EMA_200")
        macd_prev = get(prev, "MACD")
        macd_signal_prev = get(prev, "MACD_Signal")

        if any(v is None for v in [close, ema_200, ema_21, macd_prev, macd_signal_prev]):
            return 0

        # 1. Trend filter
        if close <= ema_200:
            return 0

        # 2. Price above short EMA
        if close <= ema_21:
            return 0

        # 3. Bullish MACD cross: MACD(t-1) <= MACD_Signal(t-1) AND MACD(t) > MACD_Signal(t)
        if macd_prev > macd_signal_prev:
            return 0
        if macd <= macd_signal:
            return 0

        # 4. Optional EMA50 trend-strength filter
        if self.cfg.ta2_use_ema50_filter:
            ema_50 = get(last, "EMA_50")
            if ema_50 is None or ema_50 <= ema_200:
                return 0

        return 1

    def _generate_signal(self, currency: str, ta_score: int,
                        current_value_usdc: float, percentage_change: float,
                        macd_sell: bool, ema50_blocks_buy: bool = False) -> tuple:
        """
        Generate BUY/SELL/HOLD signal based on continuous TA score and portfolio rules.

        Signal is derived from the graded ta_score and the explicit exit rules:
        - SELL when MACD < MACD_Signal OR Close < EMA_21 (exit rule)
        - BUY when ta_score >= _BUY_THRESHOLD and not blocked by EMA50 filter
        - HOLD otherwise

        Portfolio override rules (applied first):
        - Rule 1: If profit > take_profit_percentage: SELL (highest priority, overrides TA)
        - Rule 2: If holdings >= TRADE_THRESHOLD AND loss > stop_loss_percentage: SELL
        - Rule 3: If holdings < TRADE_THRESHOLD: no SELL (even if TA says sell, unless Rule 1)

        Args:
            currency: Currency symbol
            ta_score: Continuous graded TA score (higher = more bullish)
            current_value_usdc: Current value in USDC
            percentage_change: Percentage change since last purchase
            macd_sell: True if MACD < MACD_Signal or Close < EMA_21 (exit rule)
            ema50_blocks_buy: True if EMA50 filter is enabled and blocks BUY

        Returns:
            Tuple of (signal, priority) where:
            - signal: "BUY", "SELL", or "HOLD"
            - priority: 1 for Rule 1 (take profit),
                       2 for Rule 2 (stop loss), 3 for TA-based
        """
        trade_threshold = self.cfg.trade_threshold
        take_profit_pct = self.cfg.take_profit_percentage
        stop_loss_pct = self.cfg.stop_loss_percentage

        # Rule 1: If profit > take_profit_percentage, force SELL (highest priority, overrides TA)
        if percentage_change > take_profit_pct:
            log.info(f"{currency}: Profit > {take_profit_pct}% -> SELL (Rule 1 take profit)")
            return "SELL", 1

        # Check if holdings are below threshold
        if current_value_usdc < trade_threshold:
            # Rule 3: If holdings < TRADE_THRESHOLD, no SELL (even if TA says sell)
            if macd_sell:
                log.info(f"{currency}: Holdings < TRADE_THRESHOLD -> no SELL (Rule 3, despite TA exit, ta_score={ta_score})")
                return "HOLD", 3
        else:
            # Rule 2: If holdings >= TRADE_THRESHOLD and loss > stop_loss_percentage, force SELL (high priority)
            if percentage_change < -stop_loss_pct:
                log.info(f"{currency}: Loss > {stop_loss_pct}% -> SELL (Rule 2 stop loss)")
                return "SELL", 2

        # Exit rule: MACD bearish OR Close < EMA_21 → SELL
        if macd_sell:
            return "SELL", 3

        # BUY if score indicates strong bullish setup and not blocked by EMA50 filter
        if ta_score >= self._BUY_THRESHOLD and not ema50_blocks_buy:
            return "BUY", 3

        return "HOLD", 3

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
            
            # Calculate graded TA score
            ta_score = self._calculate_ta_score(ta_df)

            # Extract signal context (MACD sell condition, EMA50 filter)
            macd_sell, ema50_blocks_buy = self._extract_signal_context(ta_df)
            
            # Generate signal with priority
            signal, priority = self._generate_signal(
                currency_upper, ta_score, current_value_usdc, percentage_change,
                macd_sell=macd_sell, ema50_blocks_buy=ema50_blocks_buy
            )
            
            # Create recommendation
            recommendation = {
                'currency': currency_upper,
                'percentage_change': f"{percentage_change:.2f}",
                'ta_score': ta_score,
                'signal': signal,
                'priority': priority,
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
        - Sort by priority ascending (Rule 1 first, then Rule 2, then TA-based)
        - Within same priority:
          - BUY candidates: highest ta_score first (strongest bullish first)
          - SELL candidates: lowest ta_score first (strongest bearish first)
        
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
        # 1. Priority ascending (1=Rule 1 comes first)
        # 2. BUY before SELL within same priority (signal_order: BUY=0, SELL=1)
        # 3. BUY: highest ta_score first (-ta_score ascending)
        #    SELL: lowest ta_score first (ta_score ascending)
        def _sort_key(rec):
            if rec['signal'] == 'BUY':
                return (rec['priority'], 0, -rec['ta_score'])
            else:  # SELL
                return (rec['priority'], 1, rec['ta_score'])

        active_recommendations.sort(key=_sort_key)
        
        log.info(f"Selected {len(active_recommendations)} recommendations after filtering HOLD signals")
        for rec in active_recommendations:
            log.info(f"  {rec['signal']}: {rec['currency']} "
                    f"(priority={rec['priority']}, ta_score={rec['ta_score']})")
        
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


def rebalance_portfolio_main(cfg: Config) -> None:
    """
    Main entry point for portfolio rebalancing.
    Called from main.py when --rebalance-portfolio flag is set.
    Raises SystemExit(1) on failure.

    Args:
        cfg: Application configuration.
    """
    rebalancer = RebalancePortfolio(cfg)
    success = rebalancer.run()
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

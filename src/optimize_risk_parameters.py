#!/usr/bin/env python3
"""
OptimizeRiskParameters - hitta historiskt bästa take-profit och stop-loss per valuta.

Detta är ett analyssteg bredvid backtesting. Det använder nedladdad historik,
beräknar samma TA-indikatorer och signaler som live-rebalanseringen, och
simulerar long-only trades över ett fast parametergrid. Simuleringen håller en
enkel per-valuta-portfölj med cash/units: BUY öppnar position när portföljen
inte redan äger valutan, SELL stänger positionen, och take-profit/stop-loss
ligger ovanpå TA-reglerna som extra exitvillkor.

Resultat sparas till:
DATA_AREA_ROOT_DIR/output/risk_optimization/risk_parameters.csv
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from .backtest import Backtest, MIN_CANDLES_FOR_TA
from .config import Config
from .rebalance_portfolio import RebalancePortfolio

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Konservativt grid i procent. Justera här om större sökyta behövs.
TAKE_PROFIT_GRID = [float(v) for v in range(2, 21)]
STOP_LOSS_GRID = [float(v) for v in range(2, 16)]


class OptimizeRiskParameters:
    """Beräkna optimala TAKE_PROFIT_PERCENTAGE och STOP_LOSS_PERCENTAGE per valuta."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.data_root = Path(cfg.data_area_root_dir)
        self.output_root = self.data_root / "output" / "risk_optimization"
        self._backtest = Backtest(cfg)
        self._rebalancer = RebalancePortfolio(cfg)

    def _ta_signal(self, window: pd.DataFrame) -> str:
        """Beräkna ren TA-signal med samma algoritm som live-rebalanseringen."""
        macd_sell, ema50_blocks_buy = self._rebalancer._extract_signal_context(window)
        if macd_sell:
            return "SELL"

        ta_score = self._rebalancer._calculate_ta_score(window)
        if ta_score >= self._rebalancer._BUY_THRESHOLD and not ema50_blocks_buy:
            return "BUY"

        return "HOLD"

    def _precompute_ta_signals(self, ta_df: pd.DataFrame) -> List[str]:
        """Beräkna TA-signaler en gång och återanvänd dem för hela parametergridet."""
        signals = ["HOLD"] * len(ta_df)
        start_idx = max(MIN_CANDLES_FOR_TA, 2)

        for t in range(start_idx, len(ta_df)):
            signals[t] = self._ta_signal(ta_df.iloc[: t + 1])

        return signals

    def _simulate_parameters(
        self,
        currency: str,
        ta_df: pd.DataFrame,
        take_profit_pct: float,
        stop_loss_pct: float,
        ta_signals: Optional[List[str]] = None,
        close_prices: Optional[List[float]] = None,
    ) -> Dict:
        """
        Simulera en parameterkombination.

        Startkapital är normaliserat till 1.0 USDC för jämförbarhet mellan
        valutor. Strategin går all-in vid BUY när inget innehav finns och
        säljer hela positionen vid TA SELL, take-profit eller stop-loss.
        """
        cash = 1.0
        units = 0.0
        entry_price: Optional[float] = None
        peak_value = cash
        max_drawdown_pct = 0.0
        trades = 0
        winning_trades = 0
        signals = ta_signals or self._precompute_ta_signals(ta_df)
        prices = close_prices or [
            float(v) if v is not None and not pd.isna(v) else 0.0
            for v in ta_df["Close"].tolist()
        ]

        start_idx = max(MIN_CANDLES_FOR_TA, 2)
        if len(ta_df) <= start_idx:
            return self._result_row(
                currency, take_profit_pct, stop_loss_pct, 0.0, 0, 0.0, 0.0
            )

        for t in range(start_idx, len(ta_df)):
            price = prices[t]
            if price <= 0:
                continue

            signal = signals[t]

            if units <= 0:
                if signal == "BUY":
                    units = cash / price
                    cash = 0.0
                    entry_price = price
                portfolio_value = cash
            else:
                portfolio_value = units * price
                assert entry_price is not None
                change_pct = (price / entry_price - 1.0) * 100.0

                should_sell = (
                    change_pct >= take_profit_pct
                    or change_pct <= -stop_loss_pct
                    or signal == "SELL"
                )
                if should_sell:
                    cash = units * price
                    units = 0.0
                    trades += 1
                    if change_pct > 0:
                        winning_trades += 1
                    entry_price = None
                    portfolio_value = cash

            peak_value = max(peak_value, portfolio_value)
            if peak_value > 0:
                drawdown_pct = (peak_value - portfolio_value) / peak_value * 100.0
                max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        if units > 0:
            final_price = prices[-1]
            cash = units * final_price
            units = 0.0
            trades += 1
            if entry_price is not None and final_price > entry_price:
                winning_trades += 1

        total_return_pct = (cash - 1.0) * 100.0
        win_rate_pct = (winning_trades / trades * 100.0) if trades else 0.0

        return self._result_row(
            currency,
            take_profit_pct,
            stop_loss_pct,
            total_return_pct,
            trades,
            win_rate_pct,
            max_drawdown_pct,
        )

    def _result_row(
        self,
        currency: str,
        take_profit_pct: float,
        stop_loss_pct: float,
        total_return_pct: float,
        trades: int,
        win_rate_pct: float,
        max_drawdown_pct: float,
    ) -> Dict:
        return {
            "currency": currency,
            "take_profit_percentage": f"{take_profit_pct:.2f}",
            "stop_loss_percentage": f"{stop_loss_pct:.2f}",
            "total_return_pct": f"{total_return_pct:.2f}",
            "trades": trades,
            "win_rate_pct": f"{win_rate_pct:.2f}",
            "max_drawdown_pct": f"{max_drawdown_pct:.2f}",
        }

    def _optimize_currency(self, currency: str, ta_df: pd.DataFrame) -> Optional[Dict]:
        """Testa hela gridet och returnera bästa rad för en valuta."""
        best: Optional[Dict] = None
        ta_signals = self._precompute_ta_signals(ta_df)
        close_prices = [
            float(v) if v is not None and not pd.isna(v) else 0.0
            for v in ta_df["Close"].tolist()
        ]

        for take_profit_pct in TAKE_PROFIT_GRID:
            for stop_loss_pct in STOP_LOSS_GRID:
                row = self._simulate_parameters(
                    currency,
                    ta_df,
                    take_profit_pct,
                    stop_loss_pct,
                    ta_signals,
                    close_prices,
                )
                if best is None or self._is_better(row, best):
                    best = row

        return best

    def _is_better(self, candidate: Dict, current: Dict) -> bool:
        """Sortera på avkastning, sedan lägre drawdown, sedan fler trades."""
        candidate_key = (
            float(candidate["total_return_pct"]),
            -float(candidate["max_drawdown_pct"]),
            int(candidate["trades"]),
        )
        current_key = (
            float(current["total_return_pct"]),
            -float(current["max_drawdown_pct"]),
            int(current["trades"]),
        )
        return candidate_key > current_key

    def _save_results(self, rows: List[Dict]) -> bool:
        self.output_root.mkdir(parents=True, exist_ok=True)
        output_file = self.output_root / "risk_parameters.csv"
        fieldnames = [
            "currency",
            "take_profit_percentage",
            "stop_loss_percentage",
            "total_return_pct",
            "trades",
            "win_rate_pct",
            "max_drawdown_pct",
        ]

        try:
            with open(output_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            log.info("Risk parameter optimization saved: %s", output_file)
            return True
        except Exception as e:
            log.error("Error saving risk optimization results: %s", e)
            return False

    def run(self) -> bool:
        log.info("=== Starting OptimizeRiskParameters ===")
        rows: List[Dict] = []

        for currency in self.cfg.currencies:
            currency_upper = currency.upper()
            history_df = self._backtest._load_history(currency_upper)
            if history_df is None or history_df.empty:
                log.warning("Skipping %s - no history data", currency_upper)
                continue

            ta_df = self._backtest._compute_full_ta(history_df, currency_upper)
            if ta_df is None or ta_df.empty:
                log.warning("Skipping %s - could not calculate TA", currency_upper)
                continue

            best = self._optimize_currency(currency_upper, ta_df)
            if best is not None:
                rows.append(best)
                log.info(
                    "%s best TP=%s SL=%s return=%s%% trades=%s",
                    currency_upper,
                    best["take_profit_percentage"],
                    best["stop_loss_percentage"],
                    best["total_return_pct"],
                    best["trades"],
                )

        return self._save_results(rows)


def optimize_risk_parameters_main(cfg: Config) -> None:
    optimizer = OptimizeRiskParameters(cfg)
    success = optimizer.run()
    if not success:
        log.error("OptimizeRiskParameters failed")
        raise SystemExit(1)


if __name__ == "__main__":
    from .assert_env import assert_env_and_report

    try:
        config = assert_env_and_report()
    except Exception as exc:
        log.error("Config could not be loaded: %s", exc)
        raise SystemExit(2)

    ok = OptimizeRiskParameters(config).run()
    raise SystemExit(0 if ok else 1)

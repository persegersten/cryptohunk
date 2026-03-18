#!/usr/bin/env python3
"""
Backtest - Historisk simulering av TA2 och rebalansering kombinerat.

Läser historisk data från DATA_AREA_ROOT_DIR/history/<currency>/<currency>_history.csv,
beräknar tekniska indikatorer och simulerar TA2-signaler kombinerat med
rebalanseringsregler (take-profit, stop-loss) över hela den tillgängliga historiken.

Resultatet sparas i DATA_AREA_ROOT_DIR/output/backtesting.csv.

Varje rad i resultatet representerar ett ljus (candle) för en valuta och innehåller:
- timestamp_ms: tidsstämpel (Close_Time_ms eller Open_Time_ms)
- currency: valutasymbol
- close: stängningspris vid detta ljus
- ta_signal: rå TA2-signal (-1=SÄLJA, 0=HÅLLA, 1=KÖPA)
- signal: rekommenderad åtgärd efter åsidosättningsregler (BUY/SELL/HOLD)
- trade_executed: simulerat utfört köp/sälj/håll
- cash_usdc: tillgänglig kassa i USDC efter handel
- holdings: antal enheter av valutan i portföljen
- holdings_value_usdc: värde av innehav i USDC vid aktuellt pris
- total_value_usdc: totalt portföljvärde (kassa + innehav)
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from .config import Config
from .rebalance_portfolio import RebalancePortfolio
from .technical_analysis import TechnicalAnalysis

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Minsta antal ljus innan simuleringen börjar, för att EMA_200 ska ha stabiliserats.
# TA2-algoritmen kräver minst 9 rader (LOOKBACK+1), men 200 ger meningsfull EMA_200.
MIN_CANDLES_FOR_TA = 200


class Backtest:
    """Historisk simulering av TA2 och rebalansering kombinerat."""

    # Starttkapital i USDC per valuta för simuleringen
    INITIAL_USDC_PER_CURRENCY = 1000.0

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.data_root = Path(cfg.data_area_root_dir)
        self.history_root = self.data_root / "history"
        self.output_root = self.data_root / "output"

        # Återanvänd TechnicalAnalysis för indikatorberäkningar
        self._ta = TechnicalAnalysis(cfg)
        # Återanvänd RebalancePortfolio för TA2-signal och åsidosättningsregler
        self._rebalancer = RebalancePortfolio(cfg)

    def _load_history(self, currency: str) -> Optional[pd.DataFrame]:
        """Läs historik-CSV för en valuta. Returnerar None vid fel."""
        csv_file = self.history_root / currency / f"{currency}_history.csv"
        if not csv_file.exists():
            log.error("Historikfil saknas för %s: %s", currency, csv_file)
            return None
        try:
            df = pd.read_csv(csv_file)
            log.info("Läste historik för %s: %d rader", currency, len(df))
            return df
        except Exception as e:
            log.error("Fel vid läsning av historikfil för %s: %s", currency, e)
            return None

    def _compute_full_ta(self, history_df: pd.DataFrame, currency: str) -> Optional[pd.DataFrame]:
        """
        Beräkna alla TA-indikatorer för hela historiken.

        Återanvänder beräkningsmetoderna i TechnicalAnalysis.
        """
        if "Close" not in history_df.columns:
            log.error("Close-kolumn saknas i historiken för %s", currency)
            return None

        result_df = pd.DataFrame()

        if "Open_Time_ms" in history_df.columns:
            result_df["Open_Time_ms"] = history_df["Open_Time_ms"].values
        if "Close_Time_ms" in history_df.columns:
            result_df["Close_Time_ms"] = history_df["Close_Time_ms"].values

        prices = history_df["Close"]
        result_df["Close"] = prices.values

        try:
            result_df["RSI_14"] = self._ta._calculate_rsi(prices, period=14).values
            result_df["EMA_12"] = self._ta._calculate_ema(prices, period=12).values
            result_df["EMA_21"] = self._ta._calculate_ema(prices, period=21).values
            result_df["EMA_26"] = self._ta._calculate_ema(prices, period=26).values
            result_df["EMA_50"] = self._ta._calculate_ema(prices, period=50).values
            result_df["EMA_200"] = self._ta._calculate_ema(prices, period=200).values
            macd_line, signal_line, _ = self._ta._calculate_macd(prices)
            result_df["MACD"] = macd_line.values
            result_df["MACD_Signal"] = signal_line.values
        except Exception as e:
            log.error("Fel vid beräkning av TA-indikatorer för %s: %s", currency, e)
            return None

        return result_df

    def _simulate_currency(self, currency: str, ta_df: pd.DataFrame) -> List[Dict]:
        """
        Simulera backtesting för en valuta steg för steg.

        För varje ljus (candle) från MIN_CANDLES_FOR_TA:
        1. Beräkna TA2-signal med data upp till och inklusive detta ljus.
        2. Applicera åsidosättningsregler (take-profit, stop-loss).
        3. Simulera handel baserat på rekommendationen.
        4. Registrera portföljstatus.

        Returnerar lista med poster, en per ljus.
        """
        records: List[Dict] = []

        # Portföljstatus för denna valuta
        cash_usdc = self.INITIAL_USDC_PER_CURRENCY
        holdings = 0.0
        entry_price: Optional[float] = None

        start_idx = max(MIN_CANDLES_FOR_TA, 9)  # EMA_200-stabilitet och TA2-LOOKBACK

        if len(ta_df) <= start_idx:
            log.warning(
                "Otillräckligt med data för %s (behöver > %d rader, har %d)",
                currency,
                start_idx,
                len(ta_df),
            )
            return records

        for t in range(start_idx, len(ta_df)):
            # Fönster av TA-data upp till och inklusive tidpunkt t
            window = ta_df.iloc[: t + 1]
            last = window.iloc[-1]

            current_close = last.get("Close")
            if current_close is None or pd.isna(current_close) or float(current_close) <= 0:
                continue
            current_close = float(current_close)

            # Portföljstatus
            holdings_value = holdings * current_close
            current_value_usdc = holdings_value

            if holdings > 0 and entry_price and entry_price > 0:
                percentage_change = (current_close - entry_price) / entry_price * 100.0
            else:
                percentage_change = 0.0

            # Beräkna TA2-signal
            ta_signal = self._rebalancer._calculate_ta2_signal(window)

            # Applicera åsidosättningsregler
            signal, _priority = self._rebalancer._generate_signal(
                currency=currency,
                ta_score=ta_signal,
                current_value_usdc=current_value_usdc,
                percentage_change=percentage_change,
            )

            # Simulera handel
            trade_executed = "HOLD"
            if signal == "BUY" and holdings == 0 and cash_usdc > 0:
                holdings = cash_usdc / current_close
                entry_price = current_close
                cash_usdc = 0.0
                trade_executed = "BUY"
                log.debug(
                    "%s BUY vid %.8f (innehav=%.8f enheter)", currency, current_close, holdings
                )
            elif signal == "SELL" and holdings > 0:
                cash_usdc = holdings * current_close
                holdings = 0.0
                entry_price = None
                trade_executed = "SELL"
                log.debug("%s SELL vid %.8f (kassa=%.4f USDC)", currency, current_close, cash_usdc)

            total_value = cash_usdc + holdings * current_close

            # Tidsstämpel
            timestamp_ms: object = ""
            if "Close_Time_ms" in window.columns:
                ts = last.get("Close_Time_ms")
                if ts is not None and not pd.isna(ts):
                    timestamp_ms = int(ts)
            elif "Open_Time_ms" in window.columns:
                ts = last.get("Open_Time_ms")
                if ts is not None and not pd.isna(ts):
                    timestamp_ms = int(ts)

            records.append(
                {
                    "timestamp_ms": timestamp_ms,
                    "currency": currency,
                    "close": round(current_close, 8),
                    "ta_signal": ta_signal,
                    "signal": signal,
                    "trade_executed": trade_executed,
                    "cash_usdc": round(cash_usdc, 4),
                    "holdings": round(holdings, 8),
                    "holdings_value_usdc": round(holdings * current_close, 4),
                    "total_value_usdc": round(total_value, 4),
                }
            )

        return records

    def _save_results(self, records: List[Dict]) -> bool:
        """Spara backtestresultat till CSV-fil."""
        self.output_root.mkdir(parents=True, exist_ok=True)
        output_file = self.output_root / "backtesting.csv"

        fieldnames = [
            "timestamp_ms",
            "currency",
            "close",
            "ta_signal",
            "signal",
            "trade_executed",
            "cash_usdc",
            "holdings",
            "holdings_value_usdc",
            "total_value_usdc",
        ]

        try:
            with open(output_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(records)
            log.info("Backtestresultat sparat: %s (%d rader)", output_file, len(records))
            return True
        except Exception as e:
            log.error("Fel vid sparande av backtestresultat: %s", e)
            return False

    def run(self) -> bool:
        """
        Kör backtesting för alla konfigurerade valutor.

        Returnerar True vid framgång, False vid fel.
        """
        log.info("=== Startar Backtest (TA2 + rebalansering) ===")
        log.info(
            "Startkapital: %.2f USDC per valuta, valutor: %s",
            self.INITIAL_USDC_PER_CURRENCY,
            self.cfg.currencies,
        )

        all_records: List[Dict] = []

        for currency in self.cfg.currencies:
            currency_upper = currency.upper()
            log.info("Processar %s...", currency_upper)

            history_df = self._load_history(currency_upper)
            if history_df is None or history_df.empty:
                log.warning("Hoppar över %s – ingen historikdata", currency_upper)
                continue

            ta_df = self._compute_full_ta(history_df, currency_upper)
            if ta_df is None or ta_df.empty:
                log.warning("Hoppar över %s – kunde inte beräkna TA", currency_upper)
                continue

            records = self._simulate_currency(currency_upper, ta_df)
            all_records.extend(records)
            log.info("Backtest %s: %d poster genererade", currency_upper, len(records))

        if not all_records:
            log.warning("Inga backtestposter genererades")

        return self._save_results(all_records)


def backtest_main(cfg: Config) -> None:
    """
    Entrypoint för backtesting, anropas från main.py när --backtest-flaggan är satt.
    Kastar SystemExit(1) vid fel.
    """
    bt = Backtest(cfg)
    success = bt.run()
    if not success:
        log.error("Backtest misslyckades")
        raise SystemExit(1)


if __name__ == "__main__":
    """
    Kör från kommandoraden. Hämtar konfiguration via assert_env_and_report().
    Exempel:
      python3 -m src.backtest
    """
    from .assert_env import assert_env_and_report

    try:
        cfg = assert_env_and_report()
    except Exception as e:
        log.error("Konfig kunde inte laddas: %s", e)
        raise SystemExit(2)

    success = Backtest(cfg).run()
    raise SystemExit(0 if success else 1)

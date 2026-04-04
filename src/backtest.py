#!/usr/bin/env python3
"""
Backtest - Historisk simulering av TA/TA2-strategin på nedladdad historikdata.

Läser historisk data från DATA_AREA_ROOT_DIR/history/<currency>_history.csv,
beräknar tekniska indikatorer och simulerar signaler över hela den tillgängliga
historiken.

Stödjer båda strategierna:
- TA2 (long-only trend-following pullback) – standardläge
- TA (poängbaserad) – används vid use_ta2=False

TRADE_THRESHOLD-reglerna (take-profit, stop-loss, min-innehav) som används i live-
rebalansering tillämpas INTE, för att ge en rättvisande bild av strategin i sig.

Resultaten sparas som en fil per valuta i
DATA_AREA_ROOT_DIR/output/backtesting/<CURRENCY>_backtesting.csv.

Varje rad i resultatet representerar ett ljus (candle) för en valuta och innehåller:
- timestamp_ms: tidsstämpel (Close_Time_ms eller Open_Time_ms)
- currency: valutasymbol
- ta_signal: rå signal (-1=SÄLJA, 0=HÅLLA, 1=KÖPA)
- signal: rekommenderad åtgärd (BUY/SELL/HOLD)
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, List

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
    """Historisk simulering av TA/TA2-strategin."""

    def __init__(self, cfg: Config, use_ta2: bool = True):
        self.cfg = cfg
        self.use_ta2 = use_ta2
        self.data_root = Path(cfg.data_area_root_dir)
        self.history_root = self.data_root / "history"
        self.output_root = self.data_root / "output" / "backtesting"

        # Återanvänd TechnicalAnalysis för indikatorberäkningar
        self._ta = TechnicalAnalysis(cfg)
        # Återanvänd RebalancePortfolio för signal-beräkning
        self._rebalancer = RebalancePortfolio(cfg)

    def _load_history(self, currency: str) -> Optional[pd.DataFrame]:
        """Läs historik-CSV för en valuta. Returnerar None vid fel."""
        csv_file = self.history_root / f"{currency}_history.csv"
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
        1. Beräkna signal med vald strategi (TA eller TA2) med data upp till och
           inklusive detta ljus.
        2. Mappa råa signalen direkt (BUY/SELL/HOLD).
           TRADE_THRESHOLD-reglerna (take-profit, stop-loss, min-innehav) tillämpas
           INTE vid backtesting, för att ge en rättvisande bild av strategin.

        Returnerar lista med poster, en per ljus.
        """
        records: List[Dict] = []

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

            # Beräkna signal med vald strategi
            if self.use_ta2:
                ta_signal = self._rebalancer._calculate_ta2_signal(window)
            else:
                ta_signal = self._rebalancer._calculate_ta_score(last)

            # Mappa signalen direkt – TRADE_THRESHOLD-regler hoppas över
            if ta_signal >= 1:
                signal = "BUY"
            elif ta_signal <= -1:
                signal = "SELL"
            else:
                signal = "HOLD"

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
                    "ta_signal": ta_signal,
                    "signal": signal,
                }
            )

        return records

    def _save_results(self, currency: str, records: List[Dict]) -> bool:
        """Spara backtestresultat för en valuta till CSV-fil.

        Filen sparas som <currency>_backtesting.csv i output_root.
        """
        self.output_root.mkdir(parents=True, exist_ok=True)
        output_file = self.output_root / f"{currency}_backtesting.csv"

        fieldnames = [
            "timestamp_ms",
            "currency",
            "ta_signal",
            "signal",
        ]

        try:
            with open(output_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(records)
            log.info("Backtestresultat sparat: %s (%d rader)", output_file, len(records))
            return True
        except Exception as e:
            log.error("Fel vid sparande av backtestresultat för %s: %s", currency, e)
            return False

    def run(self) -> bool:
        """
        Kör backtesting för alla konfigurerade valutor.

        Använder den strategi (TA eller TA2) som angavs vid instansiering.

        Sparar en CSV per valuta i output_root/<CURRENCY>_backtesting.csv.
        Returnerar True vid framgång, False vid fel.
        """
        strategy_name = "TA2" if self.use_ta2 else "TA"
        log.info("=== Startar Backtest (strategi: %s) ===", strategy_name)
        log.info("Valutor: %s", self.cfg.currencies)

        # Säkerställ att utdatakatalogen finns innan vi börjar
        self.output_root.mkdir(parents=True, exist_ok=True)

        success = True

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
            log.info("Backtest %s: %d poster genererade", currency_upper, len(records))

            if not self._save_results(currency_upper, records):
                success = False

        return success


def backtest_main(cfg: Config, use_ta2: bool = True) -> None:
    """
    Entrypoint för backtesting, anropas från main.py när --backtest-flaggan är satt.

    Args:
        cfg: Konfiguration.
        use_ta2: Om True, simulera TA2-strategin. Om False, simulera TA-strategin.

    Kastar SystemExit(1) vid fel.
    """
    bt = Backtest(cfg, use_ta2=use_ta2)
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

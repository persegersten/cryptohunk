#!/usr/bin/env python3
"""
TechnicalAnalysis - Beräkna tekniska indikatorer på kurshistorik.

Läser in kurshistorik från DATA_AREA_ROOT_DIR/history/<currency>/<currency>_history.csv
Beräknar följande tekniska indikatorer:
- RSI (14 perioder)
- EMA (12 perioder)
- EMA (21 perioder)
- EMA (26 perioder)
- EMA (50 perioder)
- EMA (200 perioder)
- MACD

Sparar resultatet i DATA_AREA_ROOT_DIR/ta/<currency>/<currency>_ta.csv
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional
import pandas as pd

from .config import Config

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class TechnicalAnalysis:
    """Beräkna tekniska indikatorer på historisk kursdata."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.data_root = Path(cfg.data_area_root_dir)
        self.history_root = self.data_root / "history"
        self.ta_root = self.data_root / "ta"

    def _ensure_dir(self, path: Path) -> None:
        """Skapa katalog om den inte finns."""
        path.mkdir(parents=True, exist_ok=True)

    def _read_history_csv(self, currency: str) -> Optional[pd.DataFrame]:
        """
        Läs kurshistorik från CSV-fil för given valuta.
        Returnerar DataFrame med Close-pris eller None vid fel.
        """
        currency_dir = self.history_root / currency
        csv_file = currency_dir / f"{currency}_history.csv"

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

    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """
        Beräkna RSI (Relative Strength Index).
        
        Args:
            prices: Serie med Close-priser
            period: Antal perioder (default 14)
        
        Returns:
            Serie med RSI-värden
        """
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calculate_ema(self, prices: pd.Series, period: int) -> pd.Series:
        """
        Beräkna EMA (Exponential Moving Average).
        
        Args:
            prices: Serie med Close-priser
            period: Antal perioder
        
        Returns:
            Serie med EMA-värden
        """
        return prices.ewm(span=period, adjust=False).mean()

    def _calculate_macd(self, prices: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
        """
        Beräkna MACD (Moving Average Convergence Divergence).
        
        Args:
            prices: Serie med Close-priser
        
        Returns:
            Tuple med (MACD line, Signal line, MACD histogram)
        """
        ema_12 = self._calculate_ema(prices, 12)
        ema_26 = self._calculate_ema(prices, 26)
        macd_line = ema_12 - ema_26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_histogram = macd_line - signal_line
        return macd_line, signal_line, macd_histogram

    def calculate_indicators(self, currency: str) -> Optional[pd.DataFrame]:
        """
        Beräkna alla tekniska indikatorer för en valuta.
        
        Args:
            currency: Valutasymbol (t.ex. "BTC", "ETH")
        
        Returns:
            DataFrame med alla indikatorer eller None vid fel
        """
        df = self._read_history_csv(currency)
        if df is None or df.empty:
            return None

        # Kontrollera att Close-kolumnen finns
        if "Close" not in df.columns:
            log.error("Close-kolumn saknas i historikfilen för %s", currency)
            return None

        # Skapa resultat-DataFrame
        result_df = pd.DataFrame()
        
        # Kopiera tidsinformation om den finns
        if "Open_Time_ms" in df.columns:
            result_df["Open_Time_ms"] = df["Open_Time_ms"]
        if "Close_Time_ms" in df.columns:
            result_df["Close_Time_ms"] = df["Close_Time_ms"]
        
        # Lägg till Close-pris
        result_df["Close"] = df["Close"]

        try:
            # Beräkna RSI (14 perioder)
            result_df["RSI_14"] = self._calculate_rsi(df["Close"], period=14)
            log.info("Beräknade RSI(14) för %s", currency)

            # Beräkna EMAs
            result_df["EMA_12"] = self._calculate_ema(df["Close"], period=12)
            result_df["EMA_21"] = self._calculate_ema(df["Close"], period=21)
            result_df["EMA_26"] = self._calculate_ema(df["Close"], period=26)
            result_df["EMA_50"] = self._calculate_ema(df["Close"], period=50)
            result_df["EMA_200"] = self._calculate_ema(df["Close"], period=200)
            log.info("Beräknade EMA(12, 21, 26, 50, 200) för %s", currency)

            # Beräkna MACD
            macd_line, signal_line, macd_histogram = self._calculate_macd(df["Close"])
            result_df["MACD"] = macd_line
            result_df["MACD_Signal"] = signal_line
            result_df["MACD_Histogram"] = macd_histogram
            log.info("Beräknade MACD för %s", currency)

            return result_df

        except Exception as e:
            log.error("Fel vid beräkning av indikatorer för %s: %s", currency, e)
            return None

    def save_ta_results(self, currency: str, ta_df: pd.DataFrame) -> bool:
        """
        Spara TA-resultat till CSV-fil.
        
        Args:
            currency: Valutasymbol
            ta_df: DataFrame med TA-indikatorer
        
        Returns:
            True vid succé, False vid fel
        """
        currency_dir = self.ta_root / currency
        self._ensure_dir(currency_dir)
        
        csv_file = currency_dir / f"{currency}_ta.csv"
        
        try:
            ta_df.to_csv(csv_file, index=False)
            log.info("Sparade TA-resultat för %s: %s", currency, csv_file)
            return True
        except Exception as e:
            log.error("Fel vid sparande av TA-resultat för %s: %s", currency, e)
            return False

    def run(self) -> bool:
        """
        Kör teknisk analys för alla konfigurerade valutor.
        
        Returns:
            True om alla valutor processades framgångsrikt, annars False
        """
        log.info("=== Startar TechnicalAnalysis ===")
        log.info("Beräknar tekniska indikatorer för valutor: %s", self.cfg.currencies)

        success_count = 0
        fail_count = 0

        for currency in self.cfg.currencies:
            try:
                log.info("Processar %s...", currency)
                ta_df = self.calculate_indicators(currency)
                
                if ta_df is None or ta_df.empty:
                    log.warning("Ingen data att spara för %s", currency)
                    fail_count += 1
                    continue
                
                if self.save_ta_results(currency, ta_df):
                    success_count += 1
                    log.info("Framgångsrikt processad: %s", currency)
                else:
                    fail_count += 1
                    
            except Exception as e:
                log.error("Oväntat fel vid processning av %s: %s", currency, e)
                fail_count += 1

        log.info("TechnicalAnalysis klar: %d lyckades, %d misslyckades", 
                 success_count, fail_count)
        
        return fail_count == 0


# Module-level convenience function
def technical_analysis_main(cfg: Config) -> None:
    """
    Entrypoint för att köra teknisk analys från main.py eller andra moduler.
    Kastar SystemExit(1) vid fel.
    """
    log.info("=== Startar TechnicalAnalysis ===")
    ta = TechnicalAnalysis(cfg)
    success = ta.run()
    if not success:
        log.error("TechnicalAnalysis misslyckades för en eller flera valutor")
        raise SystemExit(1)


# CLI-stöd: körs direkt
if __name__ == "__main__":
    """
    Kör från kommandoraden. Hämtar env via assert_env_and_report() för att få Config.
    Ex:
      python3 src/technical_analysis.py
    """
    from .assert_env import assert_env_and_report
    
    try:
        cfg = assert_env_and_report()
    except Exception as e:
        log.error("Konfig kunde inte laddas: %s", e)
        raise SystemExit(2)

    success = TechnicalAnalysis(cfg).run()
    raise SystemExit(0 if success else 1)

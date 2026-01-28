#!/usr/bin/env python3
"""
CollectData - Datainhämtning för CryptoHunk2.0 (hunk2)

Denna version innehåller en enkel tids-synk mot Binance (/api/v3/time)
så att signerade requests får en timestamp i Binance-tid och undviker
fel -1021 "Timestamp for this request was ... ahead/behind the server's time".
"""
import os
import sys
import csv
import logging
import json
import requests
import hmac
import hashlib
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from .config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


class CollectData:
    """Hantera datainsamling från Binance API med tids-synk för signerade endpoints."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.base_url = cfg.binance_base_url.rstrip("/")
        self.api_key = cfg.binance_key
        self.api_secret = cfg.binance_secret
        self.data_root = Path(cfg.data_area_root_dir)
        # server_time - local_time in ms (can be negative). None = not synced yet.
        self.time_offset_ms: Optional[int] = None

    def _ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def _sign_request(self, query_string: str) -> str:
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def _fetch_server_time(self) -> int:
        """Hämta serverTime från Binance (/api/v3/time). Returnerar serverTime (ms)."""
        url = f"{self.base_url}/api/v3/time"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        j = r.json()
        server_time = int(j.get("serverTime"))
        return server_time

    def sync_time(self) -> None:
        """Synka lokal tid mot Binance och lagra offset i ms."""
        try:
            server_time = self._fetch_server_time()
            local_time = int(time.time() * 1000)
            self.time_offset_ms = int(server_time - local_time)
            log.info("Tids-synk mot Binance klar: server_time=%s local_time=%s offset_ms=%s",
                     server_time, local_time, self.time_offset_ms)
        except Exception as e:
            # don't raise here — keep time_offset None so caller can decide
            log.warning("Kunde inte hämta Binance serverTime: %s", e)
            self.time_offset_ms = None

    def _effective_timestamp(self) -> int:
        """Returnera timestamp att använda i signerade requests (ms)."""
        if self.time_offset_ms is None:
            # försök synk om vi inte redan har offset
            self.sync_time()
        now_ms = int(time.time() * 1000)
        if self.time_offset_ms is None:
            # fallback: använd lokal tid om sync misslyckades
            return now_ms
        return now_ms + int(self.time_offset_ms)

    def _signed_get(self, endpoint: str, params: Dict[str, Any], retry_on_time_error: bool = True) -> requests.Response:
        """
        Skicka signerad GET request till Binance. Använder synced timestamp.
        Vid -1021 (timestamp) försöker vi sync_time() och retry en gång.
        """
        params = dict(params or {})
        params["timestamp"] = self._effective_timestamp()

        qs = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
        signature = self._sign_request(qs)
        url = f"{self.base_url}{endpoint}?{qs}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.api_key}

        try:
            r = requests.get(url, headers=headers, timeout=20)
            # Don't raise here yet — inspect body for Binance error codes as well
            if r.status_code >= 400:
                # try parse JSON error
                try:
                    err = r.json()
                    # Binance signed timestamp error code is -1021
                    if isinstance(err, dict) and err.get("code") == -1021 and retry_on_time_error:
                        log.warning("Binance returned -1021 (timestamp). Försöker synka tid och retry...")
                        self.sync_time()
                        # retry once with fresh timestamp
                        return self._signed_get(endpoint, params={k: v for k, v in params.items() if k != "timestamp"}, retry_on_time_error=False)
                except Exception:
                    pass
                r.raise_for_status()
            return r
        except requests.RequestException as e:
            log.error("RequestException för %s: %s", endpoint, e)
            raise

    # --- Collect currency history (public klines) ---
    def collect_currency_rate_history(self) -> None:
        log.info("=== Startar CollectDataCurrencyRateHistory ===")

        history_root = self.data_root / "history"
        self._ensure_dir(history_root)

        currencies = self.cfg.currencies
        period = self.cfg.currency_history_period
        nof_elements = self.cfg.currency_history_nof_elements

        for currency in currencies:
            try:
                log.info("Hämtar kurshistorik för %s...", currency)
                symbol = f"{currency}USDT"
                endpoint = self.cfg.binance_currency_history_endpoint
                url = f"{self.base_url}{endpoint}"
                params = {"symbol": symbol, "interval": period, "limit": nof_elements}

                r = requests.get(url, params=params, timeout=20)
                r.raise_for_status()
                klines_data = r.json()
                if not klines_data:
                    log.warning("Ingen data för %s", symbol)
                    continue

                currency_dir = history_root / currency
                self._ensure_dir(currency_dir)
                csv_file = currency_dir / f"{currency}_history.csv"
                self._write_klines_to_csv(klines_data, csv_file)
                log.info("Kurshistorik sparad för %s: %s", currency, csv_file)
            except Exception as e:
                log.error("Fel vid hämtning av kurshistorik för %s: %s", currency, e)

    def _write_klines_to_csv(self, klines_data: List[List[Any]], csv_file: Path) -> None:
        headers = [
            "Open_Time_ms", "Open", "High", "Low", "Close", "Volume",
            "Close_Time_ms", "Quote_Asset_Volume", "Number_of_Trades",
            "Taker_Buy_Base_Asset_Volume", "Taker_Buy_Quote_Asset_Volume"
        ]
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for k in klines_data:
                writer.writerow([
                    int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]),
                    int(k[6]), float(k[7]), int(k[8]), float(k[9]), float(k[10])
                ])

    # --- Portfolio (signed) ---
    def collect_portfolio(self) -> None:
        log.info("=== Startar CollectDataPortfolio ===")
        portfolio_dir = self.data_root / "portfolio"
        self._ensure_dir(portfolio_dir)

        try:
            balance = self._get_account_balance()

            # Tillåtna assets = union av Config.currencies + Config.allowed_quote_assets (uppercased)
            allowed_assets = {c.upper() for c in (self.cfg.currencies or [])}
            allowed_assets.update({q.upper() for q in (self.cfg.allowed_quote_assets or [])})

            # Konfiguration: spara noll-saldon eller inte (förslaget: False)
            include_zero_balances = False

            filtered_total = {}
            balances = balance.get("balances") if isinstance(balance, dict) else None
            if isinstance(balances, list):
                for b in balances:
                    asset = (b.get("asset") or "").upper()
                    if asset not in allowed_assets:
                        continue
                    free = b.get("free", "0")
                    locked = b.get("locked", "0")
                    try:
                        total = float(free or 0) + float(locked or 0)
                    except Exception:
                        # Om parse misslyckas: inkludera för säkerhets skull (så att inget viktigt försvinner)
                        total = None
                    if total is None or include_zero_balances or (isinstance(total, (int, float)) and total > 0):
                        # Spara free/locked som str (som Binance returnerar) för att undvika precision-överraskningar
                        filtered_total[asset] = {"free": free, "locked": locked, "total": (str(total) if total is not None else None)}
            else:
                log.warning("Kunde inte läsa 'balances' som lista från account-responsen; sparar inget portfolio-innehåll.")

            portfolio_data = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "balances": filtered_total,
                "saved_assets_count": len(filtered_total),
            }

            portfolio_file = portfolio_dir / "portfolio.json"
            with open(portfolio_file, "w", encoding="utf-8") as fh:
                json.dump(portfolio_data, fh, indent=2, ensure_ascii=False)
            log.info("Portfolio data sparad: %s (assets=%d)", portfolio_file, len(filtered_total))
        except Exception as e:
            log.error("Fel vid hämtning av portfolio-data: %s", e)

    def _get_exchange_info(self) -> Dict[str, Any]:
        endpoint = self.cfg.binance_exchange_info_endpoint
        url = f"{self.base_url}{endpoint}"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json()

    def _get_account_balance(self) -> Dict[str, Any]:
        endpoint = "/api/v3/account"
        r = self._signed_get(endpoint, params={})
        return r.json()

    # --- Trades (signed) ---
    def collect_trade_history(self) -> None:
        log.info("=== Startar CollectDataTradeHistory ===")
        trades_dir = self.data_root / "trades"
        self._ensure_dir(trades_dir)

        try:
            all_trades = []
            exchange_info = self._get_exchange_info()

            # --- Begränsa symbols till endast de par vi faktiskt bryr oss om ---
            allowed_bases = {c.upper() for c in self.cfg.currencies}
            # Använd konfigurerbara quote-assets från Config
            allowed_quotes = {q.upper() for q in (self.cfg.allowed_quote_assets or [])}

            symbols = []
            for s_info in exchange_info.get("symbols", []):
                base = (s_info.get("baseAsset") or "").upper()
                quote = (s_info.get("quoteAsset") or "").upper()
                sym = s_info.get("symbol")
                if base in allowed_bases and quote in allowed_quotes:
                    symbols.append(sym)

            if not symbols:
                # fallback: om filtret ger tomt (oväntat), hämta alla symboler
                log.warning("Inga symboler hittades efter filtrering — fallback till alla symboler.")
                symbols = [s_info["symbol"] for s_info in exchange_info.get("symbols", [])]

            log.info("Hämtar tradehistorik för %s symboler (filtrerade)...", len(symbols))
            for sym in symbols:
                try:
                    trades = self._get_trades_for_symbol(sym)
                    if trades:
                        all_trades.extend(trades)
                except Exception as e:
                    log.warning("Fel vid hämtning av trades för %s: %s", sym, e)

            trades_file = trades_dir / "trades.json"
            with open(trades_file, "w", encoding="utf-8") as fh:
                json.dump(all_trades, fh, indent=2, ensure_ascii=False)
            log.info("Tradehistorik sparad: %s (%d trades)", trades_file, len(all_trades))
        except Exception as e:
            log.error("Fel vid hämtning av tradehistorik: %s", e)

    def _get_trades_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        endpoint = self.cfg.binance_my_trades_endpoint
        params = {"symbol": symbol, "limit": 1000}
        r = self._signed_get(endpoint, params)
        try:
            return r.json() if isinstance(r.json(), list) else []
        except Exception:
            return []

    def run(self) -> None:
        log.info("Startar CollectData-modulen...")
        try:
            self.collect_currency_rate_history()
            self.collect_portfolio()
            self.collect_trade_history()
            log.info("CollectData avslutad framgångsrikt!")
        except Exception as e:
            log.error("Kritiskt fel i CollectData: %s", e)
            sys.exit(1)


# Backwards-compatible module-level entrypoints ------------------------------------------------

def collect_data(cfg: Config) -> None:
    """
    Befintlig funktion som tidigare användes.
    """
    collector = CollectData(cfg)
    collector.run()

def collect_all(cfg: Config) -> None:
    """
    Backwards-compatible namn (main/jobb kan anropa collect_all(cfg)).
    Långsiktigt kan ni använda CollectData.run() eller collect_data(cfg).
    """
    collect_data(cfg)
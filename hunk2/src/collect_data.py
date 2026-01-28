from __future__ import annotations

import csv
import json
import time
import hmac
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlencode

import requests

from .config import Config


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


class CollectData:
    """
    CollectData class for fetching data from Binance with time synchronization.
    
    Time synchronization: Fetches Binance /api/v3/time and stores time offset
    (server_time - local_time) for use in signed timestamps for signed endpoints.
    Retries once on Binance error code -1021 by re-syncing and retrying.
    """
    
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.time_offset: Optional[int] = None
        self._sync_time()
    
    def _sync_time(self) -> None:
        """
        Synchronize time with Binance server.
        Fetches /api/v3/time and stores the offset (server_time - local_time).
        """
        url = self.cfg.binance_base_url.rstrip("/") + "/api/v3/time"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            server_time = resp.json()["serverTime"]
            local_time = int(time.time() * 1000)
            self.time_offset = server_time - local_time
            print(f"Time synchronized with Binance. Offset: {self.time_offset}ms")
        except Exception as e:
            print(f"Warning: Failed to sync time with Binance: {e}")
            self.time_offset = 0
    
    def _get_timestamp(self) -> int:
        """
        Get current timestamp adjusted with Binance server offset.
        """
        local_time = int(time.time() * 1000)
        return local_time + (self.time_offset or 0)
    
    def _sign_request(self, params: dict) -> str:
        """
        Sign a request with HMAC SHA256.
        Adds timestamp and signature to params.
        """
        params["timestamp"] = self._get_timestamp()
        query_string = urlencode(params)
        signature = hmac.new(
            self.cfg.binance_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return query_string + f"&signature={signature}"
    
    def _request_with_retry(self, url: str, params: dict, signed: bool = False, timeout: int = 30) -> requests.Response:
        """
        Make a request with retry logic for timestamp errors (-1021).
        """
        headers = {}
        if signed:
            headers["X-MBX-APIKEY"] = self.cfg.binance_key
            query_string = self._sign_request(params)
            full_url = f"{url}?{query_string}"
        else:
            full_url = url
        
        try:
            if signed:
                resp = requests.get(full_url, headers=headers, timeout=timeout)
            else:
                resp = requests.get(full_url, params=params, timeout=timeout)
            resp.raise_for_status()
            
            # Check for Binance error code -1021 (timestamp error)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("code") == -1021:
                        print("Received -1021 timestamp error, re-syncing time and retrying...")
                        self._sync_time()
                        # Retry once
                        if signed:
                            query_string = self._sign_request(params)
                            full_url = f"{url}?{query_string}"
                            resp = requests.get(full_url, headers=headers, timeout=timeout)
                        else:
                            resp = requests.get(full_url, params=params, timeout=timeout)
                        resp.raise_for_status()
                except (ValueError, KeyError):
                    pass  # Not JSON or no error code
            
            return resp
        except requests.exceptions.HTTPError as e:
            # Check if response contains -1021 error
            try:
                error_data = e.response.json()
                if error_data.get("code") == -1021:
                    print("Received -1021 timestamp error, re-syncing time and retrying...")
                    self._sync_time()
                    # Retry once
                    if signed:
                        query_string = self._sign_request(params)
                        full_url = f"{url}?{query_string}"
                        resp = requests.get(full_url, headers=headers, timeout=timeout)
                    else:
                        resp = requests.get(full_url, params=params, timeout=timeout)
                    resp.raise_for_status()
                    return resp
            except (ValueError, AttributeError):
                pass
            raise
    
    def collect_currency_rate_history(self) -> None:
        """
        Hämta klines från Binance och spara som CSV per valuta.
        
        Sparas i: DATA_AREA_ROOT_DIR/history/<currency>/<currency>_history.csv
        """
        base = Path(self.cfg.data_area_root_dir)
        out_root = base / "history"
        _ensure_dir(out_root)
        
        for cur in self.cfg.currencies:
            symbol = f"{cur}USDT"
            params = {
                "symbol": symbol,
                "interval": self.cfg.currency_history_period,
                "limit": self.cfg.currency_history_nof_elements,
            }
            
            url = self.cfg.binance_base_url.rstrip("/") + self.cfg.binance_currency_history_endpoint
            try:
                resp = self._request_with_retry(url, params, signed=False)
                data = resp.json()
                # data is list of klines (list of lists)
                
                cur_dir = out_root / cur
                _ensure_dir(cur_dir)
                
                out_file = cur_dir / f"{cur}_history.csv"
                with out_file.open("w", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    # header according to Binance kline array
                    header = [
                        "open_time",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "close_time",
                        "quote_asset_volume",
                        "number_of_trades",
                        "taker_buy_base_asset_volume",
                        "taker_buy_quote_asset_volume",
                        "ignore",
                    ]
                    writer.writerow(header)
                    for k in data:
                        writer.writerow(k)
                
                print(f"Sparad historik för {symbol} -> {out_file}")
            except Exception as e:
                print(f"Fel vid hämtning av historik för {symbol}: {e}")
                continue
    
    def collect_portfolio(self) -> None:
        """
        Hämta konto-balans. Försök använda ccxt om installerat, annars hämta exchangeInfo som fallback.
        
        Sparas i:
          - DATA_AREA_ROOT_DIR/portfolio/portfolio_<timestamp>.json (ccxt)
          - DATA_AREA_ROOT_DIR/portfolio/exchange_info.json (fallback)
        """
        base = Path(self.cfg.data_area_root_dir)
        out_root = base / "portfolio"
        _ensure_dir(out_root)
        
        try:
            import ccxt  # type: ignore
        except Exception:
            print(
                "ccxt saknas — hämtar exchange info som fallback (ingen konto-info). "
                "Installera ccxt för konto- och trade-historik."
            )
            url = self.cfg.binance_base_url.rstrip("/") + self.cfg.binance_exchange_info_endpoint
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                out_file = out_root / "exchange_info.json"
                with out_file.open("w", encoding="utf-8") as fh:
                    json.dump(resp.json(), fh, indent=2)
                print(f"Sparad exchange info -> {out_file}")
            except Exception as e:
                print(f"Fel vid hämtning av exchange info: {e}")
            return
        
        # Using ccxt to fetch balances
        try:
            exchange = ccxt.binance(
                {
                    "apiKey": self.cfg.binance_key,
                    "secret": self.cfg.binance_secret,
                    "enableRateLimit": True,
                }
            )
            balance = exchange.fetch_balance()
            out_file = out_root / f"portfolio_{_timestamp()}.json"
            with out_file.open("w", encoding="utf-8") as fh:
                json.dump(balance, fh, default=str, indent=2)
            print(f"Sparad portfolio (saldo) -> {out_file}")
        except Exception as e:
            print(f"Fel vid hämtning av portfolio via ccxt: {e}")
    
    def collect_trade_history(self) -> None:
        """
        Hämta tradehistorik för kontot via ccxt och spara per valuta.
        
        Sparas i: DATA_AREA_ROOT_DIR/trades/<currency>_trades_<timestamp>.json
        """
        base = Path(self.cfg.data_area_root_dir)
        out_root = base / "trades"
        _ensure_dir(out_root)
        
        try:
            import ccxt  # type: ignore
        except Exception:
            raise RuntimeError(
                "ccxt krävs för att hämta tradehistorik. Installera med: pip install ccxt"
            )
        
        try:
            exchange = ccxt.binance(
                {
                    "apiKey": self.cfg.binance_key,
                    "secret": self.cfg.binance_secret,
                    "enableRateLimit": True,
                }
            )
            
            for cur in self.cfg.currencies:
                symbol = f"{cur}/USDT"
                try:
                    trades = exchange.fetch_my_trades(symbol)
                except Exception as e:
                    print(f"Fel vid hämtning av trades för {symbol}: {e}")
                    trades = []
                
                out_file = out_root / f"{cur}_trades_{_timestamp()}.json"
                with out_file.open("w", encoding="utf-8") as fh:
                    json.dump(trades, fh, default=str, indent=2)
                
                print(f"Sparad trade-historik för {symbol} -> {out_file}")
        
        except Exception as e:
            print(f"Fel vid initiering av ccxt exchange för trade-historik: {e}")


# Backwards-compatible function wrappers
def collect_currency_rate_history(cfg: Config) -> None:
    """Backwards-compatible wrapper for collect_currency_rate_history."""
    collector = CollectData(cfg)
    collector.collect_currency_rate_history()


def collect_portfolio(cfg: Config) -> None:
    """Backwards-compatible wrapper for collect_portfolio."""
    collector = CollectData(cfg)
    collector.collect_portfolio()


def collect_trade_history(cfg: Config) -> None:
    """Backwards-compatible wrapper for collect_trade_history."""
    collector = CollectData(cfg)
    collector.collect_trade_history()


def collect_all(cfg: Config) -> None:
    """Orkestrera insamling: historik, portfolio, tradehistory."""
    print("Startar insamling av data...")
    collector = CollectData(cfg)
    collector.collect_currency_rate_history()
    collector.collect_portfolio()
    try:
        collector.collect_trade_history()
    except RuntimeError as e:
        print(f"Hoppar över trade-historik: {e}")
    print("Insamling klar.")


# Exports
__all__ = [
    "CollectData",
    "collect_all",
    "collect_currency_rate_history",
    "collect_portfolio",
    "collect_trade_history",
]
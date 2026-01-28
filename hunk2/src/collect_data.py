from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import List

import requests

from .config import Config


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def collect_currency_rate_history(cfg: Config) -> None:
    """
    Hämta klines från Binance och spara som CSV per valuta.

    Sparas i: DATA_AREA_ROOT_DIR/history/<currency>/<currency>_history.csv
    """
    base = Path(cfg.data_area_root_dir)
    out_root = base / "history"
    _ensure_dir(out_root)

    for cur in cfg.currencies:
        symbol = f"{cur}USDT"
        params = {
            "symbol": symbol,
            "interval": cfg.currency_history_period,
            "limit": cfg.currency_history_nof_elements,
        }

        url = cfg.binance_base_url.rstrip("/") + cfg.binance_currency_history_endpoint
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"Fel vid hämtning av historik för {symbol}: {e}")
            continue

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


def collect_portfolio(cfg: Config) -> None:
    """
    Hämta konto-balans. Försök använda ccxt om installerat, annars hämta exchangeInfo som fallback.

    Sparas i:
      - DATA_AREA_ROOT_DIR/portfolio/portfolio_<timestamp>.json (ccxt)
      - DATA_AREA_ROOT_DIR/portfolio/exchange_info.json (fallback)
    """
    base = Path(cfg.data_area_root_dir)
    out_root = base / "portfolio"
    _ensure_dir(out_root)

    try:
        import ccxt  # type: ignore
    except Exception:
        print(
            "ccxt saknas — hämtar exchange info som fallback (ingen konto-info). "
            "Installera ccxt för konto- och trade-historik."
        )
        url = cfg.binance_base_url.rstrip("/") + cfg.binance_exchange_info_endpoint
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
                "apiKey": cfg.binance_key,
                "secret": cfg.binance_secret,
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


def collect_trade_history(cfg: Config) -> None:
    """
    Hämta tradehistorik för kontot via ccxt och spara per valuta.

    Sparas i: DATA_AREA_ROOT_DIR/trades/<currency>_<quote>_trades_<timestamp>.json
    Endast filer med trades skapas.
    """
    base = Path(cfg.data_area_root_dir)
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
                "apiKey": cfg.binance_key,
                "secret": cfg.binance_secret,
                "enableRateLimit": True,
            }
        )

        for cur in cfg.currencies:
            for quote in cfg.allowed_quote_assets:
                symbol = f"{cur}/{quote}"
                try:
                    trades = exchange.fetch_my_trades(symbol)
                except Exception as e:
                    print(f"Fel vid hämtning av trades för {symbol}: {e}")
                    trades = []

                if trades:
                    out_file = out_root / f"{cur}_{quote}_trades_{_timestamp()}.json"
                    with out_file.open("w", encoding="utf-8") as fh:
                        json.dump(trades, fh, default=str, indent=2)

                    print(f"Sparad trade-historik för {symbol} -> {out_file}")

    except Exception as e:
        print(f"Fel vid initiering av ccxt exchange för trade-historik: {e}")


def collect_all(cfg: Config) -> None:
    """Orkestrera insamling: historik, portfolio, tradehistory."""
    print("Startar insamling av data...")
    collect_currency_rate_history(cfg)
    collect_portfolio(cfg)
    try:
        collect_trade_history(cfg)
    except RuntimeError as e:
        print(f"Hoppar över trade-historik: {e}")
    print("Insamling klar.")


# Exports
__all__ = [
    "collect_all",
    "collect_currency_rate_history",
    "collect_portfolio",
    "collect_trade_history",
]
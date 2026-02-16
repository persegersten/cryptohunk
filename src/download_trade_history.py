#!/usr/bin/env python3
import json
import sys
import time
from decimal import Decimal
from pathlib import Path
from collections import defaultdict

from binance.client import Client
from binance.exceptions import BinanceAPIException

# --- Läs nycklar från secrets.json ---
SECRETS_PATH = Path("secrets.json")
if not SECRETS_PATH.exists():
    raise FileNotFoundError("Filen secrets.json saknas.")

with SECRETS_PATH.open() as f:
    secrets = json.load(f)

API_KEY = secrets.get("CCXT_API_KEY")
API_SECRET = secrets.get("CCXT_API_SECRET")

if not API_KEY or not API_SECRET:
    raise ValueError("CCXT_API_KEY eller CCXT_API_SECRET saknas i secrets.json")

# --- Initiera klient ---
client = Client(API_KEY, API_SECRET)

def get_all_symbols():
    """Hämta alla TRADING-symboler från spot-börsen."""
    info = client.get_exchange_info()
    return [s["symbol"] for s in info["symbols"] if s.get("status") == "TRADING"]

def fetch_all_trades_for_symbol(symbol, rate_sleep=0.15):
    """
    Hämta *hela* trade-historiken för en symbol genom att paginera med fromId.
    Returnerar en generator som yield:ar trades i stigande id-ordning.
    """
    last_id = None
    while True:
        try:
            # Binance API: get_my_trades stödjer 'fromId' för pagination.
            # limit max 1000. Vi försöker alltid få så många som möjligt.
            params = {"symbol": symbol, "limit": 1000}
            if last_id is not None:
                params["fromId"] = last_id + 1

            batch = client.get_my_trades(**params)
        except BinanceAPIException as e:
            # Om vi t.ex. inte handlat den symbolen: tyst hoppa vidare
            # (du kan byta till loggning/stderr om du vill)
            break

        if not batch:
            break

        # sortera för säkerhets skull (bör vara stigande id)
        batch.sort(key=lambda x: x.get("id", 0))

        for t in batch:
            yield t

        # Om id inte ökar längre → slut
        new_last_id = batch[-1].get("id")
        if new_last_id is None or new_last_id == last_id:
            break
        last_id = new_last_id

        # liten paus för rate limits
        time.sleep(rate_sleep)

def main():
    symbols = get_all_symbols()

    # Summor per commissionAsset
    fee_totals = defaultdict(Decimal)

    for sym in symbols:
        for trade in fetch_all_trades_for_symbol(sym):
            # skriv varje trade som en NDJSON-rad till stdout
            print(json.dumps(trade, ensure_ascii=False))

            # uppdatera fee-summor
            asset = trade.get("commissionAsset")
            amount = trade.get("commission")
            if asset and amount is not None:
                # Binance returnerar ofta strängar för numeriska fält
                try:
                    fee_totals[asset] += Decimal(str(amount))
                except Exception:
                    # Ignorera konstiga värden
                    pass

    # Skriv en sista rad med summerad fee per asset
    fee_summary_obj = {
        "type": "fee_summary",
        "fees": {asset: str(total) for asset, total in fee_totals.items()}
    }
    print(json.dumps(fee_summary_obj, ensure_ascii=False))

if __name__ == "__main__":
    # flush direkt (bra om du pipar vidare)
    sys.stdout.reconfigure(line_buffering=True)
    main()

#!/usr/bin/env python3
"""
Steg 2: Hämta spot-trade-historik, splitta per valuta och spara som CSV.
Ny funktionalitet: Exporterar även en summeringsfil per valuta (JSON + CSV) samt en aggregerad summary JSON.

Antagande: Binance API (samma API-nycklar som i run.sh eller miljövariabler).
Kräver: requests
  pip install requests

Output:
- Original JSON med allt som laddats ner: downloaded_originals/original_trades_...json
- Per-asset trades CSV: bnb_data/trades_bnb_...csv etc.
- Per-asset summary JSON & CSV: bnb_data/summary_bnb_...json, bnb_data/summary_bnb_...csv
- Aggregerad summary JSON: downloaded_originals/summary_all_assets_...json

Summeringen innehåller:
- total_trades
- total_received_amount (summan av positiva asset_amount)
- total_sent_amount (summan av absoluta värdet av negativa asset_amount)
- net_amount (received - sent)
- total_commission (per commissionAsset)
- vwap_per_quote (för varje quoteAsset: summerad asset-volym och VWAP i den quote)
"""
from __future__ import annotations
import os
import re
import time
import hmac
import csv
import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional, DefaultDict
from collections import defaultdict

import requests

# --- Konfiguration ---
BASE_URL = "https://api.binance.com"
EXCHANGE_INFO_ENDPOINT = "/api/v3/exchangeInfo"
MY_TRADES_ENDPOINT = "/api/v3/myTrades"
ASSETS = {
    "bnb": "BNB",
    "etherum": "ETH",   # använder ETH för "etherum"
    "solana": "SOL"
}
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIRS = {
    "bnb": Path(ROOT / "trades" / "bnb_data"),
    "etherum": Path(ROOT / "trades" / "ethereum_data"),
    "solana": Path(ROOT / "trades" / "solana_data")
}
ORIGINAL_OUTPUT_DIR = Path(ROOT / "trades" / "downloaded_originals")
REQUEST_LIMIT = 1000  # max trades per request

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# --- Hjälpfunktioner för API-nycklar ---
def load_api_keys_from_env_or_runsh(runsh_path: str = "run.sh") -> Tuple[Optional[str], Optional[str]]:
    env_keys = {}
    for k in ("CCXT_API_KEY", "CCXT_API_SECRET"):
        v = os.environ.get(k)
        if v:
            env_keys[k] = v

    api_key = env_keys.get("CCXT_API_KEY")
    api_secret = env_keys.get("CCXT_API_SECRET")

    if api_key and api_secret:
        logging.info("Hämtade API-nycklar från miljövariabler.")
        return api_key, api_secret

    logging.warning("Kunde inte hitta både API_KEY och API_SECRET i run.sh.")
    raise RuntimeError


# --- Binance-signerad request ---
def sign_querystring(querystring: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), querystring.encode("utf-8"), hashlib.sha256).hexdigest()


def signed_get(endpoint: str, params: Dict[str, Any], api_key: str, api_secret: str) -> requests.Response:
    ts = int(time.time() * 1000)
    params = dict(params)
    params["timestamp"] = ts
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    signature = sign_querystring(qs, api_secret)
    url = f"{BASE_URL}{endpoint}?{qs}&signature={signature}"
    headers = {"X-MBX-APIKEY": api_key}
    r = requests.get(url, headers=headers, timeout=20)
    return r


# --- Hämta exchange info och filter symboler för asset ---
def get_exchange_info() -> Dict[str, Any]:
    r = requests.get(f"{BASE_URL}{EXCHANGE_INFO_ENDPOINT}", timeout=20)
    r.raise_for_status()
    return r.json()


def symbols_for_asset(exchange_info: Dict[str, Any], asset: str) -> List[Dict[str, Any]]:
    syms = []
    for s in exchange_info.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        if s.get("baseAsset") == asset or s.get("quoteAsset") == asset:
            syms.append(s)
    return syms


# --- Hämta trades per symbol och aggregera per asset ---
def fetch_trades_for_symbol(symbol: str, api_key: str, api_secret: str) -> List[Dict[str, Any]]:
    all_trades: List[Dict[str, Any]] = []
    params = {"symbol": symbol, "limit": REQUEST_LIMIT}
    try:
        r = signed_get(MY_TRADES_ENDPOINT, params=params, api_key=api_key, api_secret=api_secret)
        if r.status_code == 200:
            trades = r.json()
            if isinstance(trades, list):
                all_trades.extend(trades)
            else:
                logging.warning(f"OE förväntat svar för symbol {symbol}: {trades}")
        else:
            logging.error(f"Fel från Binance för symbol {symbol}: {r.status_code} - {r.text}")
    except requests.RequestException as e:
        logging.error(f"Nätverksfel vid hämtning av trades för {symbol}: {e}")
    return all_trades


def iso_time(ms: int) -> str:
    return datetime.utcfromtimestamp(ms / 1000.0).isoformat() + "Z"


def normalize_trade_for_asset(trade: Dict[str, Any], asset: str, symbol_meta: Dict[str, Any]) -> Dict[str, Any]:
    base = symbol_meta["baseAsset"]
    quote = symbol_meta["quoteAsset"]
    is_base = (base == asset)
    t = {
        "time": iso_time(trade.get("time")),
        "timestamp_ms": trade.get("time"),
        "symbol": trade.get("symbol"),
        "id": trade.get("id"),
        "orderId": trade.get("orderId"),
        "price": trade.get("price"),
        "qty": trade.get("qty"),
        "quoteQty": trade.get("quoteQty"),
        "isBuyer": trade.get("isBuyer"),
        "isMaker": trade.get("isMaker"),
        "commission": trade.get("commission"),
        "commissionAsset": trade.get("commissionAsset"),
        "asset": asset,
        "asset_is_base": is_base,
        "quoteAsset": quote,
        "baseAsset": base
    }
    try:
        qty = float(trade.get("qty", 0))
    except Exception:
        qty = 0.0
    try:
        quote_qty = float(trade.get("quoteQty", 0))
    except Exception:
        quote_qty = 0.0

    if is_base:
        asset_change = qty if trade.get("isBuyer") else -qty
    else:
        asset_change = -quote_qty if trade.get("isBuyer") else quote_qty

    t["asset_amount"] = asset_change
    # price per base in quote; keep as float if possible
    try:
        t["price_f"] = float(trade.get("price", 0))
    except Exception:
        t["price_f"] = 0.0
    try:
        t["qty_f"] = float(trade.get("qty", 0))
    except Exception:
        t["qty_f"] = 0.0
    try:
        t["quoteQty_f"] = float(trade.get("quoteQty", 0))
    except Exception:
        t["quoteQty_f"] = 0.0

    return t


def aggregate_trades_by_asset(api_key: str, api_secret: str, assets_map: Dict[str, str]) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
    exchange_info = get_exchange_info()
    trades_per_asset: Dict[str, List[Dict[str, Any]]] = {k: [] for k in assets_map.keys()}
    raw_bundle: Dict[str, Any] = {"fetched_at": int(time.time()), "per_symbol": {}}

    for k, asset in assets_map.items():
        logging.info(f"Bearbetar asset {asset} ({k})...")
        syms = symbols_for_asset(exchange_info, asset)
        if not syms:
            logging.warning(f"Inga trading-symboler hittades för asset {asset}.")
            continue
        logging.info(f"  Hittade {len(syms)} symboler som inkluderar {asset}.")
        for s in syms:
            symbol_name = s["symbol"]
            logging.info(f"    Hämtar trades för symbol {symbol_name} ...")
            trades = fetch_trades_for_symbol(symbol_name, api_key, api_secret)
            raw_bundle["per_symbol"][symbol_name] = trades
            for tr in trades:
                norm = normalize_trade_for_asset(tr, asset, s)
                trades_per_asset[k].append(norm)

    return trades_per_asset, raw_bundle


# --- Summera trades ---
def compute_summary_for_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Beräkna summering för en lista normaliserade trades för en asset.
    - summerar mottagen/såld mängd i asset-enheten (positiva/negativa asset_amount)
    - summerar commission per commissionAsset
    - beräknar VWAP per quoteAsset (använder base/quote info från varje trade)
    """
    summary: Dict[str, Any] = {
        "total_trades": 0,
        "total_received_amount": 0.0,
        "total_sent_amount": 0.0,
        "net_amount": 0.0,
        "total_commission": {},  # commissionAsset -> float
        "vwap_per_quote": {},    # quoteAsset -> {total_asset_volume, vwap_price}
    }

    # For vwap we will accumulate for each quoteAsset: total_asset_volume (in asset units) and total_quote_spent (in quote units)
    vwap_acc: DefaultDict[str, Dict[str, float]] = defaultdict(lambda: {"asset_vol": 0.0, "quote_sum": 0.0})

    for t in trades:
        summary["total_trades"] += 1
        amt = float(t.get("asset_amount", 0.0))
        if amt > 0:
            summary["total_received_amount"] += amt
        else:
            summary["total_sent_amount"] += abs(amt)
        summary["net_amount"] += amt

        # commission
        comm_asset = t.get("commissionAsset")
        try:
            comm_amount = float(t.get("commission", 0.0))
        except Exception:
            comm_amount = 0.0
        if comm_asset:
            summary["total_commission"].setdefault(comm_asset, 0.0)
            summary["total_commission"][comm_asset] += comm_amount

        # VWAP accumulation:
        # If the trade's asset was baseAsset (i.e. asset_is_base True), then price_f is price (quote per base)
        # and qty_f is base amount; so asset_vol = qty_f, quote_sum = price_f * qty_f = quoteQty_f
        # If the asset was quoteAsset (asset_is_base False), then the asset is quote: asset_amount is in quote units.
        # In that case we can treat the 'quoteAsset' as the asset's quote (i.e., the real quote is baseAsset),
        # but for VWAP we want to compute in terms of the paired asset — simpler: use trade["quoteAsset"] as the quote unit
        # and accumulate asset_vol in asset units using qty_f if asset_is_base else quoteQty_f.
        quote_asset = t.get("quoteAsset")
        is_base = bool(t.get("asset_is_base"))
        price = float(t.get("price_f", 0.0))
        qty_f = float(t.get("qty_f", 0.0))
        quote_qty_f = float(t.get("quoteQty_f", 0.0))

        if is_base:
            asset_vol = qty_f
            quote_sum = price * qty_f
            q_asset = quote_asset
        else:
            # asset is quote -> asset units are in quoteQty_f
            asset_vol = quote_qty_f
            # price is still presented as price = (quote per base). For quote-asset VWAP this is not directly meaningful.
            # But the quote-side "price" per unit of quote is 1/(price) per base unit — mixing quote/base here is messy.
            # To keep it consistent we still accumulate asset_vol (quote units) and quote_sum in terms of base*asset_vol,
            # but that produces a VWAP in base units. For clarity we will record vwap only for cases where the asset is base.
            quote_sum = 0.0
            q_asset = quote_asset

        if asset_vol and q_asset:
            acc = vwap_acc[q_asset]
            acc["asset_vol"] += asset_vol
            acc["quote_sum"] += quote_sum

    # Finalize vwap_per_quote
    for q, v in vwap_acc.items():
        asset_vol = v["asset_vol"]
        quote_sum = v["quote_sum"]
        if asset_vol > 0:
            vwap_price = quote_sum / asset_vol
        else:
            vwap_price = 0.0
        summary["vwap_per_quote"][q] = {"total_asset_volume": asset_vol, "vwap_price": vwap_price}

    # Round some floats for readability
    def r(v):
        try:
            return round(v, 12)
        except Exception:
            return v

    summary["total_received_amount"] = r(summary["total_received_amount"])
    summary["total_sent_amount"] = r(summary["total_sent_amount"])
    summary["net_amount"] = r(summary["net_amount"])
    for k in list(summary["total_commission"].keys()):
        summary["total_commission"][k] = r(summary["total_commission"][k])
    for q in list(summary["vwap_per_quote"].keys()):
        summary["vwap_per_quote"][q]["total_asset_volume"] = r(summary["vwap_per_quote"][q]["total_asset_volume"])
        summary["vwap_per_quote"][q]["vwap_price"] = r(summary["vwap_per_quote"][q]["vwap_price"])

    return summary


# --- Spara filer ---
def save_original_json(bundle: Dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    p = output_dir / f"original_trades_{ts}.json"
    p.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
    return p


def save_csv_for_asset(asset_key: str, trades: List[Dict[str, Any]], output_dir: Path) -> Optional[Path]:
    if not trades:
        logging.info(f"Inga trades att spara för {asset_key}.")
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = output_dir / f"trades_{asset_key}_{ts}.csv"
    fieldnames = [
        "time", "timestamp_ms", "symbol", "id", "orderId", "price", "qty", "quoteQty",
        "isBuyer", "isMaker", "commission", "commissionAsset", "asset", "asset_is_base", "asset_amount",
        "baseAsset", "quoteAsset"
    ]
    with open(filename, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for t in sorted(trades, key=lambda x: x.get("timestamp_ms", 0)):
            writer.writerow({k: t.get(k, "") for k in fieldnames})
    return filename


def save_summary_json(asset_key: str, summary: Dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    p = output_dir / f"summary_{asset_key}_{ts}.json"
    p.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return p


def save_summary_csv(asset_key: str, summary: Dict[str, Any], output_dir: Path) -> Path:
    """
    Skriv en kompakt CSV-rad med enklare fält. Mer komplexa fält (commission, vwap_per_quote) skrivs som JSON-sträng i kolumner.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    p = output_dir / f"summary_{asset_key}_{ts}.csv"
    fieldnames = [
        "asset_key", "total_trades", "total_received_amount", "total_sent_amount", "net_amount",
        "total_commission_json", "vwap_per_quote_json"
    ]
    with open(p, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        row = {
            "asset_key": asset_key,
            "total_trades": summary.get("total_trades", 0),
            "total_received_amount": summary.get("total_received_amount", 0),
            "total_sent_amount": summary.get("total_sent_amount", 0),
            "net_amount": summary.get("net_amount", 0),
            "total_commission_json": json.dumps(summary.get("total_commission", {}), ensure_ascii=False),
            "vwap_per_quote_json": json.dumps(summary.get("vwap_per_quote", {}), ensure_ascii=False)
        }
        writer.writerow(row)
    return p


# --- Main-run ---
def download_trades() -> Tuple[str, str, str]:
    api_key, api_secret = load_api_keys_from_env_or_runsh("run.sh")
    if not api_key or not api_secret:
        logging.error("Saknar API-nycklar. Sätt BINANCE_API_KEY och BINANCE_API_SECRET i miljön eller i run.sh.")
        return 2

    trades_per_asset, raw_bundle = aggregate_trades_by_asset(api_key, api_secret, ASSETS)

    # Spara originalfil
    original_path = save_original_json(raw_bundle, ORIGINAL_OUTPUT_DIR)
    logging.info(f"Sparade original nedladdning: {original_path}")

    saved_paths = {}
    summary_paths = {}
    per_asset_summaries = {}

    for asset_key, outdir in OUTPUT_DIRS.items():
        trades = trades_per_asset.get(asset_key, [])
        p = save_csv_for_asset(asset_key, trades, outdir)
        if p:
            logging.info(f"Sparade CSV för {asset_key}: {p}")
            saved_paths[asset_key] = str(p)
        else:
            logging.info(f"Ingen CSV-skapad för {asset_key} (inget innehåll).")

        # Beräkna och spara summary
        summary = compute_summary_for_trades(trades)
        per_asset_summaries[asset_key] = summary
        sjson = save_summary_json(asset_key, summary, outdir)
        scsv = save_summary_csv(asset_key, summary, outdir)
        logging.info(f"Sparade summary JSON för {asset_key}: {sjson}")
        logging.info(f"Sparade summary CSV för {asset_key}: {scsv}")
        summary_paths[asset_key] = {"json": str(sjson), "csv": str(scsv)}

    # Spara aggregerad summary av alla assets
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    agg_summary = {
        "generated_at": ts,
        "original_download": str(original_path),
        "per_asset": per_asset_summaries
    }
    agg_path = ORIGINAL_OUTPUT_DIR / f"summary_all_assets_{ts}.json"
    ORIGINAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    agg_path.write_text(json.dumps(agg_summary, indent=2, ensure_ascii=False))
    logging.info(f"Sparade aggregerad summary: {agg_path}")

    # Skriv ut en kort JSON-summary för pipeline-anrop
    final_summary = {
        "original": str(original_path),
        "per_asset_csv": saved_paths,
        "per_asset_summary": summary_paths,
        "aggregated_summary": str(agg_path)
    }
    print(json.dumps(final_summary))
    logging.info("Färdig med steg 2.")
    return saved_paths


if __name__ == "__main__":
    exit(download_trades() or 0)
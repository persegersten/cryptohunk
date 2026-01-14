#!/usr/bin/env python3
"""
Analyse: ladda senaste OHLCV-filer och plota x dagar bakåt, en fil per valuta.

- Valutor: bnb, ethereum, solana (en fil per valuta förväntas i respektive mapp)
- Fel kastas om data saknas eller inte täcker angivet intervall
- Använder plot_history för att rita; varje valuta sparas som en separat PNG
- end sätts till senaste gemensamma timestamp från filerna (min av max-timestamps)
"""

from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional
import pandas as pd

import ohlcv_files as of
import plot_history as ph

def _now_utc_ts() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))

def prepare_series_for_plot(filepath: str | Path, days: int, label: str = "", verbose: bool = False) -> pd.DataFrame:
    """
    Ladda fil och validera att tidsrymden i filen täcker minst `days` dagar.
    Returnerar hela DataFrame:n (inte beskuren). Beskärning sker senare gemensamt.
    Kastar RuntimeError vid bristande data.
    """
    path = Path(filepath)
    if verbose:
        print(f"[analyse] Laddar {label or path.name}: {path}")
    df = ph.load_dataframe(path)

    if df.empty:
        raise RuntimeError(f"Ingen data i filen: {path}")

    if not pd.api.types.is_datetime64_any_dtype(df.index):
        # load_dataframe försöker redan, men dubbelkolla
        try:
            df.index = pd.to_datetime(df.index)
        except Exception:
            raise RuntimeError(f"Kan inte konvertera index till datetime för fil: {path}")

    # Kontrollera att den totala tidsrymden täcker days
    span = df.index.max() - df.index.min()
    if span < pd.Timedelta(days=days):
        raise RuntimeError(f"Data för '{label or path.name}' täcker inte {days} dagar (span={span})")

    if verbose:
        print(f"[analyse] '{label or path.name}': tidsspann {df.index.min()} - {df.index.max()} (span={span})")

    return df

def plot_recent_history(days: int = 30, save_path: Optional[str] = None, verbose: bool = False) -> dict:
    """
    Hög-nivå API: plottar senaste `days` dagar för bnb, ethereum och solana.
    - end sätts till min(df.index.max()) över alla serier för att synkronisera sista tidpunkt
    - Varje valuta sparas i egen PNG i save_path (om save_path är mapp) eller i ./output
    - Om någon valuta saknar data eller inte täcker perioden så kastas RuntimeError.
    Returnerar dict med result och listan filer som skapades.
    """
    # 1) Lokalisera senaste filer
    file_bnb, file_eth, file_sol = of.locate_input_files()

    labels = ["bnb", "ethereum", "solana"]
    files = [file_bnb, file_eth, file_sol]

    # 2) Ladda och validera att varje fil innehåller minst 'days' dagar (men trimmas senare)
    dfs_full: List[pd.DataFrame] = []
    for f, lbl in zip(files, labels):
        df = prepare_series_for_plot(f, days=days, label=lbl, verbose=verbose)
        dfs_full.append(df)

    # 3) Bestäm gemensam end som min av varje series max-timestamp (så alla synkroniseras)
    end_ts = min(df.index.max() for df in dfs_full)
    start_ts = end_ts - pd.Timedelta(days=days)

    if verbose:
        print(f"[analyse] Gemensam tidsintervall: {start_ts} -> {end_ts}")

    # 4) Trimma varje serie till [start_ts, end_ts] och kontrollera att inget är tomt
    dfs_trimmed: List[pd.DataFrame] = []
    for df, lbl in zip(dfs_full, labels):
        sliced = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
        if sliced.empty:
            raise RuntimeError(f"Ingen data för '{lbl}' i intervallet {start_ts} - {end_ts}")
        if verbose:
            print(f"[analyse] '{lbl}': {len(sliced)} rader i intervallet {start_ts} - {end_ts}")
        dfs_trimmed.append(sliced)

    # 5) Bestäm utmapp för png-filer
    if save_path:
        p = Path(save_path)
        # Om en fil (.png) angavs, använd dess parent som mapp; annars använd save_path som mapp
        out_dir = p.parent if p.suffix.lower() == ".png" else p
    else:
        out_dir = Path("./output")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 6) Rita och spara en PNG per valuta
    saved_files: List[str] = []
    tag = end_ts.strftime("%Y%m%d_%H%M%S")
    for df, lbl in zip(dfs_trimmed, labels):
        fname = f"{lbl}_{days}d_{tag}.png"
        out_file = (out_dir / fname).resolve()
        if verbose:
            print(f"[analyse] Sparar diagram för '{lbl}' -> {out_file}")
        # Anropa plot_history.plot_series med single-serie list
        ph.plot_series(dfs=[df], labels=[lbl], start=start_ts, end=end_ts, save_path=out_file, verbose=verbose)
        saved_files.append(str(out_file))

    return {"ok": True, "plotted": len(dfs_trimmed), "start": str(start_ts), "end": str(end_ts), "files": saved_files}

if __name__ == "__main__":
    # Exempel / snabbtest
    import argparse
    p = argparse.ArgumentParser(description="Plot recent history for bnb/ethereum/solana (one PNG per currency)")
    p.add_argument("--days", type=int, default=30, help="Antal dagar bakåt att plotta")
    p.add_argument("--save", help="Spara PNG(s) till denna mapp (eller fil - då används filens parent). Standard: ./output")
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    args = p.parse_args()

    try:
        res = plot_recent_history(days=args.days, save_path=args.save, verbose=args.verbose)
        print("Resultat:", res)
    except Exception as e:
        print("Fel:", e)
        raise
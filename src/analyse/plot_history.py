from __future__ import annotations
from typing import List, Optional, Dict, Any
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import argparse
import json
import sys

DEFAULT_EXTENSIONS = (".csv", ".parquet", ".pkl", ".pickle", ".feather")
TIME_COL_CANDIDATES = ("date", "datetime", "timestamp", "time", "open_time", "openTimestamp")
PRICE_COL_CANDIDATES = ("close", "Close", "close_price", "price")


def find_files_for_series(series: str) -> List[Path]:
    """
    Sök efter filer som matchar serienamnet.
    - Om 'series' är en existerande filväg returneras den.
    - Annars söker vi rekursivt i nuvarande arbetskatalog efter mönster `{series}*{ext}`.
    """
    p = Path(series)
    if p.exists() and p.is_file():
        return [p]

    found: List[Path] = []
    for ext in DEFAULT_EXTENSIONS:
        pattern = f"**/{series}*{ext}"
        for f in Path(".").glob(pattern):
            if f.is_file():
                found.append(f)
    return sorted(found)


def load_dataframe(path: Path) -> pd.DataFrame:
    """Läser en fil till DataFrame och försöker sätta datetime-index."""
    ext = path.suffix.lower()
    if ext == ".csv":
        df = pd.read_csv(path)
    elif ext == ".parquet":
        df = pd.read_parquet(path)
    elif ext in (".pkl", ".pickle"):
        df = pd.read_pickle(path)
    elif ext == ".feather":
        df = pd.read_feather(path)
    else:
        raise ValueError(f"Okänd filtyp: {path}")

    # Försök hitta tidskolumn och sätt som index
    for col in TIME_COL_CANDIDATES:
        if col in df.columns:
            try:
                df[col] = pd.to_datetime(df[col])
                df = df.set_index(col)
                break
            except Exception:
                pass

    # Om index inte är datetime, försök konvertera index
    if not pd.api.types.is_datetime64_any_dtype(df.index):
        try:
            df.index = pd.to_datetime(df.index)
        except Exception:
            # Leta efter någon kolumn som ser ut som tidsstämpel och försök igen
            for c in df.columns:
                if any(tok in c.lower() for tok in ("date", "time", "timestamp")):
                    try:
                        df[c] = pd.to_datetime(df[c])
                        df = df.set_index(c)
                        break
                    except Exception:
                        continue

    return df


def choose_price_column(df: pd.DataFrame) -> Optional[str]:
    """Välj en kolumn att rita som pris."""
    for c in PRICE_COL_CANDIDATES:
        if c in df.columns:
            return c
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    return numeric_cols[0] if numeric_cols else None


def plot_series(
    dfs: List[pd.DataFrame],
    labels: List[str],
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    save_path: Optional[Path] = None,
    verbose: bool = False,
) -> None:
    plt.figure(figsize=(12, 6))
    plotted_any = False

    for df, label in zip(dfs, labels):
        if df.empty:
            if verbose:
                print(f"[plot_history] Ingen data för {label}, hoppar över")
            continue

        s = df
        if start is not None:
            s = s.loc[s.index >= start]
        if end is not None:
            s = s.loc[s.index <= end]

        if s.empty:
            if verbose:
                print(f"[plot_history] Inget data i intervallet för {label}, hoppar över")
            continue

        col = choose_price_column(s)
        if col is None:
            if verbose:
                print(f"[plot_history] Hittade ingen pris-kolumn för {label}, hoppar över")
            continue

        plt.plot(s.index, s[col], label=label)
        plotted_any = True

    if not plotted_any:
        if verbose:
            print("[plot_history] Inga serier ritades (ingen giltig data).")
        return

    plt.legend()
    plt.grid(True)
    plt.xlabel("Tid")
    plt.ylabel("Pris")
    plt.title("Tidsserie-historik")
    plt.tight_layout()

    if save_path:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path)
        if verbose:
            print(f"[plot_history] Sparade diagram till {save_path}")
    else:
        try:
            plt.show()
        except Exception:
            # Headless: spara temporärt
            tmp = Path(".").resolve() / "history_plot.png"
            plt.savefig(tmp)
            if verbose:
                print(f"[plot_history] Headless-miljö: sparade bild till {tmp}")


def _parse_timestamp(value: Optional[Any]) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    try:
        return pd.to_datetime(value)
    except Exception:
        return None


def run(series_inputs: Any, properties: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Huvudentré för pipeline:
    - series_inputs: str eller lista av str. Varje str kan vara filväg eller serie-identifierare.
    - properties: dict med inställningar (se modul-dokumentation).

    Returnerar dict med resultat.
    """
    if properties is None:
        properties = {}

    plot_flag = properties.get("plot_history") or properties.get("plotHistory") or False
    if not plot_flag:
        return {"ok": True, "skipped": True, "reason": "plot_history property not set"}

    verbose = bool(properties.get("verbose", False))

    if isinstance(series_inputs, str):
        series_list = [series_inputs]
    else:
        series_list = list(series_inputs)

    start = _parse_timestamp(properties.get("start"))
    end = _parse_timestamp(properties.get("end"))
    save_path = properties.get("save_path")

    dfs: List[pd.DataFrame] = []
    labels: List[str] = []

    for s in series_list:
        if verbose:
            print(f"[plot_history] Letar efter filer för serie '{s}'")
        files = find_files_for_series(s)
        if not files:
            if verbose:
                print(f"[plot_history] Hittade inga filer för serie '{s}'")
            continue

        parts: List[pd.DataFrame] = []
        for f in files:
            try:
                df = load_dataframe(f)
                parts.append(df)
                if verbose:
                    print(f"[plot_history] Läste {f} (rader={len(df)})")
            except Exception as e:
                if verbose:
                    print(f"[plot_history] Kunde inte läsa {f}: {e}")

        if not parts:
            continue

        try:
            combined = pd.concat(parts).sort_index()
            combined = combined[~combined.index.duplicated(keep="last")]
            dfs.append(combined)
            labels.append(s)
        except Exception as e:
            if verbose:
                print(f"[plot_history] Misslyckades att slå ihop data för {s}: {e}")

    if not dfs:
        return {"ok": False, "message": "Inga tidsserier att plotta"}

    plot_series(dfs, labels, start=start, end=end, save_path=Path(save_path) if save_path else None, verbose=verbose)
    return {"ok": True, "plotted": len(dfs)}


def _cli() -> None:
    p = argparse.ArgumentParser(description="Rita historikfiler för en eller flera tidsserier")
    p.add_argument("--series", "-s", action="append", required=True, help="Serie-identifierare eller fil (flera allowed)")
    p.add_argument("--plot-history", dest="plot_history", action="store_true", help="Tvinga plot")
    p.add_argument("--start", help="Starttid (ISO)")
    p.add_argument("--end", help="Endtid (ISO)")
    p.add_argument("--save", help="Spara PNG till denna sökväg istället för att visa")
    p.add_argument("--props-json", help="JSON-fil med properties (överskriver CLI-flaggor)")
    p.add_argument("--verbose", action="store_true", help="Visa detaljerad logg")
    args = p.parse_args()

    props: Dict[str, Any] = {}
    if args.props_json:
        try:
            with open(args.props_json, "r", encoding="utf-8") as fh:
                props = json.load(fh)
        except Exception as e:
            print(f"Kunde inte läsa props-json: {e}")
            sys.exit(1)

    if args.plot_history:
        props["plot_history"] = True
    if args.start:
        props["start"] = args.start
    if args.end:
        props["end"] = args.end
    if args.save:
        props["save_path"] = args.save
    if args.verbose:
        props["verbose"] = True

    res = run(args.series, props)
    print("Resultat:", res)


if __name__ == "__main__":
    _cli()

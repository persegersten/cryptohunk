#!/usr/bin/env python3
from pathlib import Path
import shutil
import logging
from typing import Tuple, List
import os
import download_binance_ohlcv as dl

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent / "ohlcv_data"
HISTORY_DIR = ROOT / "history"
DATA_FOLDERS = {
    "bnb": ROOT / "bnb_data",
    "ethereum": ROOT / "ethereum_data",
    "solana": ROOT / "solana_data",
}

def download_history():
    # move old CSVs to history
    rotate_history()
    
    # download OHLCV using programmatic wrappers
    # the module should provide a run(symbol, data_folder) or similar; try common names
    for sym, folder in (("BNBUSDT", DATA_FOLDERS["bnb"]), ("ETHUSDT", DATA_FOLDERS["ethereum"]), ("SOLUSDT", DATA_FOLDERS["solana"])):
        ensure_dir(folder)
        dl.run(symbol=sym, data_folder=str(folder))
        

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def rotate_history():
    ensure_dir(HISTORY_DIR)
    for folder in DATA_FOLDERS.values():
        if not folder.exists():
            continue
        for f in folder.iterdir():
            if f.is_file():
                shutil.move(str(f), str(HISTORY_DIR / f.name))

def find_latest_file(folder: Path) -> Path | None:
    files = [p for p in folder.glob("*") if p.is_file()]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime)
    return files[-1]

def locate_input_files() -> Tuple[str, str, str]:
    file_bnb = find_latest_file(DATA_FOLDERS["bnb"])
    file_eth = find_latest_file(DATA_FOLDERS["ethereum"])
    file_sol = find_latest_file(DATA_FOLDERS["solana"])
    if not file_bnb or not file_eth or not file_sol:
        missing = [str(p) for k,p in DATA_FOLDERS.items() if not find_latest_file(p)]
        raise RuntimeError(f"Missing files in: {missing}")
    return str(file_bnb), str(file_eth), str(file_sol)


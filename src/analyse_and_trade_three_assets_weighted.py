#!/usr/bin/env python3
"""
Python replacement for analyse_and_trade_three_assets_weighted.sh

This runner imports and calls functions directly (no subprocess).
It expects the following programmatic entrypoints to exist:
 - schedule_gate.run(...) or schedule_gate.main()
 - download_portfolio.run() or download_portfolio.main()
 - download_binance_ohlcv.run(symbol, folder) or download_binance_ohlcv.main(...)
 - the TA agent function: src.ta_signal_agent_live_three_assets.run_agent(...)
If some of those modules lack a run_* function, add a small wrapper in each module mirroring the pattern used in the TA agent above.
"""

from pathlib import Path
import shutil
import logging
from typing import Tuple, List
import os
from ohlcv_files import download_history,locate_input_files

# Import the agent function directly
from ta_signal_agent_live_three_assets import run_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main(dry_run: bool, skip_download_history: bool, sched_grace: int, sched_at_hours: list[int], sched_time_zone: str):
    # Optional: call schedule gate programmatically if schedule_gate exposes a run() function
    try:
        import schedule_gate as schedule_gate
        log.info("Schedule gate params: grace_minutes=%s, at_hours=%s, time_zone=%s", sched_grace, sched_at_hours, sched_time_zone)
        if not schedule_gate.run(grace_minutes=sched_grace, at_hours=sched_at_hours, time_zone=sched_time_zone):
            return
    except Exception:
        raise

    if not skip_download_history:
        try:
            download_history()
        except Exception:
            raise
    else:
        print("DOWNLOAD_HISTORY är satt. Skip download history")

    # locate CSVs and call the agent directly
    csvA, csvB, csvC = locate_input_files()
    snapshot = run_agent(
        csvA=csvA,
        csvB=csvB,
        csvC=csvC,
        symbols="BNB/USDC,ETH/USDC,SOL/USDC",
        exchange="binance",
        dry_run=dry_run,
    )
    log.info("Agent finished")

def is_trade_run() -> bool:
    return os.getenv("TRADE_DRY_RUN") in ("1", "true", "True", "YES", "yes")

def is_download_history() -> bool:
    return os.getenv("SKIP_DOWNLOAD_HISTORY") in ("1", "true", "True", "YES", "yes")

def _parse_int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        log.warning("Invalid integer for %s: %r. Falling back to default %s", name, val, default)
        return default

def _parse_str_env(name: str, default: str) -> str:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    try:
        return val
    except ValueError:
        log.warning("Invalid string for %s: %r. Falling back to default %s", name, val, default)
        return default

def _parse_hours_env(name: str, default: List[int]) -> List[int]:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    parts = [p.strip() for p in val.split(",") if p.strip() != ""]
    try:
        hours = [int(p) for p in parts]
        return hours
    except ValueError:
        log.warning("Invalid hours list for %s: %r. Expected comma-separated integers. Falling back to default %s", name, val, default)
        return default

if __name__ == "__main__":
    # Read schedule parameters from environment variables with sensible defaults.
    # Environment variables:
    # - SCHEDULE_GRACE_MINUTES (int) default 5
    # - SCHEDULE_AT_HOURS (comma-separated ints) default "0,4,8,12,16,20"
    # - SCHEDULE_TIME_ZONE (str) default "Europe/Stockholm"
    grace = _parse_int_env("SCHEDULE_GRACE_MINUTES", 5)
    at_hours = _parse_hours_env("SCHEDULE_AT_HOURS", [0, 4, 8, 12, 16, 20])
    time_zone = _parse_str_env("SCHEDULE_TIME_ZONE", "Europe/Stockholm")

    dry_run=is_trade_run()
    skip_download=is_download_history()
    main(dry_run, skip_download, grace, at_hours, time_zone)


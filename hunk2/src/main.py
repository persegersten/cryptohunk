"""
Entrypoint / orchestrator för CryptoHunk2.0

Kör först AssertEnv (steg 1) för att ladda/validera konfiguration.
Här är platsen där övriga steg (var och en i egen fil) kommer att anropas.
"""
import sys
import argparse

from .assert_env import assert_env_and_report, load_config_from_env


def main():
    parser = argparse.ArgumentParser(description="CryptoHunk2.0 - orchestrator")
    parser.add_argument("--dump-config", action="store_true", help="Skriv ut parsad konfiguration (ej hemliga värden)")
    args = parser.parse_args()

    try:
        cfg = assert_env_and_report()
    except Exception as e:
        print("Fel vid validering av miljövariabler:", e, file=sys.stderr)
        sys.exit(2)

    if args.dump_config:
        # Endast icke-hemliga värden för översikt
        print("\nKonfigurationsöversikt (säkra värden maskade):")
        print(f" CURRENCIES = {cfg.currencies}")
        print(f" BINANCE_BASE_URL = {cfg.binance_base_url}")
        print(f" DATA_AREA_ROOT_DIR = {cfg.data_area_root_dir}")
        print(f" CURRENCY_HISTORY_PERIOD = {cfg.currency_history_period}")
        print(f" CURRENCY_HISTORY_NOF_ELEMENTS = {cfg.currency_history_nof_elements}")
        print(f" TRADE_THRESHOLD = {cfg.trade_threshold}")
        print(f" DRY_RUN = {cfg.dry_run}")

    # Här kommer anrop till nästa steg när de implementeras, t.ex.:
    # from .fetch_history import fetch_history_for_all
    # fetch_history_for_all(cfg)
    #
    # from .analyze import analyze_signals
    # analyze_signals(cfg)
    #
    # from .execute_trades import execute_trades
    # execute_trades(cfg)

    print("\nAssertEnv klart. (Vidare steg saknas i denna ursprungliga commit.)")


if __name__ == "__main__":
    main()
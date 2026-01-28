"""
Entrypoint / orchestrator för CryptoHunk2.0

Kör först AssertEnv (steg 1) för att ladda/validera konfiguration.
Här anropas också CleanData (steg 2) och CollectData (steg 3) när flaggor anges.
"""
import sys
import argparse

from .assert_env import assert_env_and_report
from .clean_data import clean_data_area
from .collect_data import collect_all as collect_data_all
from .validate_collected_data import validate_collected_data


def main():
    parser = argparse.ArgumentParser(description="CryptoHunk2.0 - orchestrator")
    parser.add_argument(
        "--dump-config",
        action="store_true",
        help="Skriv ut parsad konfiguration (ej hemliga värden)",
    )
    parser.add_argument(
        "--clean-data",
        action="store_true",
        help="Töm DATA_AREA_ROOT_DIR innan vidare körning",
    )
    parser.add_argument(
        "--collect-data",
        action="store_true",
        help="Hämta historik, portfolio och trade-historik",
    )
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

    if args.clean_data:
        print("Rensar data-arean...")
        try:
            clean_data_area(cfg)
            print("Data-arean är rensad.")
        except Exception as e:
            print(f"Fel vid rensning av data-arean: {e}", file=sys.stderr)
            sys.exit(3)

    if args.collect_data:
        print("Startar insamling av data (CollectData)...")
        collect_data_all(cfg)
    
    validate_collected_data(cfg)

    print("\nKlar.")


if __name__ == "__main__":
    main()
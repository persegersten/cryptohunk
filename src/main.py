"""
Entrypoint / orchestrator för CryptoHunk2.0

Kör först AssertEnv (steg 1) för att ladda/validera konfiguration.
Här anropas också CleanData (steg 2) och CollectData (steg 3) när flaggor anges.
"""
import sys
import csv
import argparse
from pathlib import Path

from .assert_env import assert_env_and_report
from .clean_data import clean_data_area
from .collect_data import collect_all as collect_data_all, CollectData
from .validate_collected_data import validate_collected_data
from .summarize_portfolio import summarize_portfolio_main
from .technical_analysis import technical_analysis_main
from .rebalance_portfolio import rebalance_portfolio_main
from .create_trade_plan import create_trade_plan_main
from .execute_trade_plan import execute_trade_plan_main
from .visualize_history import visualize_history_main
from .ftp_upload import ftp_upload_main
from .backtest import backtest_main


def main():
    parser = argparse.ArgumentParser(description="CryptoHunk2.0 - orchestrator")
    parser.add_argument(
        "--dump-config",
        action="store_true",
        help="Print parsed configuration (excluding secret values)",
    )
    parser.add_argument(
        "--clean-data",
        action="store_true",
        help="Empty DATA_AREA_ROOT_DIR before continuing",
    )
    parser.add_argument(
        "--collect-data",
        action="store_true",
        help="Fetch history, portfolio, and trade history",
    )
    parser.add_argument(
        "--run-ta",
        action="store_true",
        help="Run technical analysis on historical data",
    )
    parser.add_argument(
        "--rebalance-portfolio",
        action="store_true",
        help="Generate buy/sell recommendations based on TA signals and holdings",
    )
    parser.add_argument(
        "--create-trade-plan",
        action="store_true",
        help="Create a trade plan based on portfolio and recommendations",
    )
    parser.add_argument(
        "--execute-trades",
        action="store_true",
        help="Execute trades on Binance according to the trade plan",
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Generate an interactive price history chart with buy/sell markers",
    )
    parser.add_argument(
        "--ftp-upload",
        action="store_true",
        help="Upload HTML files matching FTP_HTML_REGEXP via FTP",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run historical simulation (backtesting) with TA2 and rebalancing on downloaded history data",
    )
    args = parser.parse_args()

    try:
        cfg = assert_env_and_report()
    except Exception as e:
        print("Error validating environment variables:", e, file=sys.stderr)
        sys.exit(2)

    if args.dump_config:
        # Endast icke-hemliga värden för översikt
        print("\nConfiguration overview (safe values masked):")
        print(f" CURRENCIES = {cfg.currencies}")
        print(f" BINANCE_BASE_URL = {cfg.binance_base_url}")
        print(f" DATA_AREA_ROOT_DIR = {cfg.data_area_root_dir}")
        print(f" CURRENCY_HISTORY_PERIOD = {cfg.currency_history_period}")
        print(f" CURRENCY_HISTORY_NOF_ELEMENTS = {cfg.currency_history_nof_elements}")
        print(f" TRADE_THRESHOLD = {cfg.trade_threshold}")
        print(f" DRY_RUN = {cfg.dry_run}")

    if args.clean_data:
        print("Cleaning data area...")
        try:
            clean_data_area(cfg)
            print("Data area cleaned.")
        except Exception as e:
            print(f"Error cleaning data area: {e}", file=sys.stderr)
            sys.exit(3)

    if args.collect_data:
        print("Starting data collection (CollectData)...")
        collect_data_all(cfg)

        print("Starting portfolio summary...")
        summarize_portfolio_main(cfg)

    if args.run_ta:
        print("Starting technical analysis (TechnicalAnalysis)...")
        technical_analysis_main(cfg)

        print("Starting collected data validation...")
        validate_collected_data(cfg)

    if args.rebalance_portfolio:
        print("Starting portfolio rebalancing (RebalancePortfolio)...")
        rebalance_portfolio_main(cfg)

    if args.create_trade_plan:
        print("Creating trade plan (CreateTradePlan)...")
        create_trade_plan_main(cfg)

    if args.execute_trades:
        print("Executing trades (ExecuteTradePlan)...")
        execute_trade_plan_main(cfg)

    # Om handel utfördes och visualisering ska köras: ladda ner färsk
    # trades.json från Binance så att senaste handeln syns i diagrammet.
    if args.execute_trades and args.visualize:
        trade_plan_file = Path(cfg.data_area_root_dir) / "output" / "rebalance" / "trade_plan.csv"
        has_trades = False
        if trade_plan_file.exists():
            with open(trade_plan_file, "r", encoding="utf-8") as f:
                rows = list(csv.reader(f))
                has_trades = len(rows) > 1  # header + at least one trade
        if has_trades:
            print("Downloading fresh trades.json from Binance (for visualization)...")
            CollectData(cfg).collect_trade_history()

    if args.backtest:
        print("Starting historical simulation (Backtest)...")
        backtest_main(cfg)

    if args.visualize:
        print("Generating price history chart (VisualizeHistory)...")
        visualize_history_main(cfg)

    if args.ftp_upload:
        print("Uploading HTML files via FTP (FtpUpload)...")
        ftp_upload_main(cfg)

    print("\nDone.")


if __name__ == "__main__":
    main()

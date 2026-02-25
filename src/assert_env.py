"""
AssertEnv - verifiera att nödvändiga env-variabler finns och bygg Config-objektet.

Miljövariabler som hanteras:
- CURRENCIES (kommaseparerad lista, ex "BNB,ETH,SOL")
- BINANCE_SECRET
- BINANCE_KEY
- BINANCE_BASE_URL (om ej satt används https://api.binance.com)
- BINANCE_CURRENCY_HISTORY_ENDPOINT (om ej satt används "/api/v3/klines")
- BINANCE_EXCHANGE_INFO_ENDPOINT (om ej satt används "/api/v3/exchangeInfo")
- BINANCE_MY_TRADES_ENDPOINT (om ej satt används "/api/v3/myTrades")
- BINANCE_TRADING_URL (måste sättas)
- DRY_RUN (valfritt, true/false)
- DATA_AREA_ROOT_DIR (måste sättas)
- CURRENCY_HISTORY_PERIOD (måste sättas)
- CURRENCY_HISTORY_NOF_ELEMENTS (måste sättas, int)
- TRADE_THRESHOLD (måste sättas, float)
- TAKE_PROFIT_PERCENTAGE (valfritt, float, default: 10.0)
- STOP_LOSS_PERCENTAGE (valfritt, float, default: 6.0)
- QUOTE_ASSETS (valfritt, ex "USDT,USDC" — vilka quote-valutor vi vill hämta trades för)
- TA2_USE_EMA50_FILTER (valfritt, true/false, default: false)
"""
import os
from typing import List
from .config import Config


def _parse_bool(value: str) -> bool:
    if value is None:
        return False
    v = value.strip().lower()
    return v in ("1", "true", "yes", "y", "t")


def _parse_currencies(value: str) -> List[str]:
    if not value:
        return []
    parts = [p.strip().upper() for p in value.split(",") if p.strip()]
    return parts


def load_config_from_env() -> Config:
    env = os.environ

    # defaults
    defaults = {
        "BINANCE_BASE_URL": "https://api.binance.com",
        "BINANCE_CURRENCY_HISTORY_ENDPOINT": "/api/v3/klines",
        "BINANCE_EXCHANGE_INFO_ENDPOINT": "/api/v3/exchangeInfo",
        "BINANCE_MY_TRADES_ENDPOINT": "/api/v3/myTrades",
        # default quote assets om QUOTE_ASSETS ej är satt
        "QUOTE_ASSETS": "USDT,USDC",
    }

    missing = []

    # Required (must be present)
    required_keys = [
        "CURRENCIES",
        "BINANCE_SECRET",
        "BINANCE_KEY",
        "BINANCE_TRADING_URL",
        "DATA_AREA_ROOT_DIR",
        "CURRENCY_HISTORY_PERIOD",
        "CURRENCY_HISTORY_NOF_ELEMENTS",
        "TRADE_THRESHOLD",
    ]

    for k in required_keys:
        if not env.get(k):
            missing.append(k)

    if missing:
        raise EnvironmentError(
            "Följande miljövariabler saknas eller är tomma: " + ", ".join(missing)
        )

    # parse
    currencies = _parse_currencies(env.get("CURRENCIES", ""))
    if not currencies:
        raise EnvironmentError("CURRENCIES måste innehålla minst en valuta.")

    binance_secret = env.get("BINANCE_SECRET", "").strip()
    binance_key = env.get("BINANCE_KEY", "").strip()
    binance_trading_url = env.get("BINANCE_TRADING_URL", "").strip()
    data_area_root_dir = env.get("DATA_AREA_ROOT_DIR", "").strip()
    currency_history_period = env.get("CURRENCY_HISTORY_PERIOD", "").strip()

    # numeric conversions with error messages
    try:
        currency_history_nof_elements = int(env.get("CURRENCY_HISTORY_NOF_ELEMENTS", "0"))
    except ValueError:
        raise EnvironmentError("CURRENCY_HISTORY_NOF_ELEMENTS måste vara ett heltal.")

    try:
        trade_threshold = float(env.get("TRADE_THRESHOLD", "0"))
    except ValueError:
        raise EnvironmentError("TRADE_THRESHOLD måste vara ett tal (float).")

    try:
        take_profit_percentage = float(env.get("TAKE_PROFIT_PERCENTAGE", "10.0"))
    except ValueError:
        raise EnvironmentError("TAKE_PROFIT_PERCENTAGE måste vara ett tal (float).")

    try:
        stop_loss_percentage = float(env.get("STOP_LOSS_PERCENTAGE", "6.0"))
    except ValueError:
        raise EnvironmentError("STOP_LOSS_PERCENTAGE måste vara ett tal (float).")

    dry_run = _parse_bool(env.get("DRY_RUN", "false"))
    ta2_use_ema50_filter = _parse_bool(env.get("TA2_USE_EMA50_FILTER", "false"))

    binance_base_url = env.get("BINANCE_BASE_URL", defaults["BINANCE_BASE_URL"]).strip()
    binance_currency_history_endpoint = env.get(
        "BINANCE_CURRENCY_HISTORY_ENDPOINT", defaults["BINANCE_CURRENCY_HISTORY_ENDPOINT"]
    ).strip()
    binance_exchange_info_endpoint = env.get(
        "BINANCE_EXCHANGE_INFO_ENDPOINT", defaults["BINANCE_EXCHANGE_INFO_ENDPOINT"]
    ).strip()
    binance_my_trades_endpoint = env.get(
        "BINANCE_MY_TRADES_ENDPOINT", defaults["BINANCE_MY_TRADES_ENDPOINT"]
    ).strip()

    # Parse quote assets (kan vara ex "USDT,USDC" — default om env ej satt)
    quote_assets_raw = env.get("QUOTE_ASSETS", defaults["QUOTE_ASSETS"])
    allowed_quote_assets = _parse_currencies(quote_assets_raw)
    if not allowed_quote_assets:
        # Minimalt skydd: sätt default om parsing misslyckas
        allowed_quote_assets = _parse_currencies(defaults["QUOTE_ASSETS"])

    # Valfria FTP-inställningar
    ftp_host = env.get("FTP_HOST", "").strip() or None
    ftp_dir = env.get("FTP_DIR", "").strip() or None
    ftp_username = env.get("FTP_USERNAME", "").strip() or None
    ftp_password = env.get("FTP_PASSWORD", "").strip() or None
    ftp_html_regexp = env.get("FTP_HTML_REGEXP", "").strip() or None

    cfg = Config(
        currencies=currencies,
        binance_secret=binance_secret,
        binance_key=binance_key,
        binance_base_url=binance_base_url,
        binance_currency_history_endpoint=binance_currency_history_endpoint,
        binance_exchange_info_endpoint=binance_exchange_info_endpoint,
        binance_my_trades_endpoint=binance_my_trades_endpoint,
        binance_trading_url=binance_trading_url,
        dry_run=dry_run,
        data_area_root_dir=data_area_root_dir,
        currency_history_period=currency_history_period,
        currency_history_nof_elements=currency_history_nof_elements,
        trade_threshold=trade_threshold,
        take_profit_percentage=take_profit_percentage,
        stop_loss_percentage=stop_loss_percentage,
        allowed_quote_assets=allowed_quote_assets,
        ftp_host=ftp_host,
        ftp_dir=ftp_dir,
        ftp_username=ftp_username,
        ftp_password=ftp_password,
        ftp_html_regexp=ftp_html_regexp,
        ta2_use_ema50_filter=ta2_use_ema50_filter,
        raw_env={k: env.get(k) for k in list(env.keys())},
    )

    return cfg


def assert_env_and_report() -> Config:
    """
    Kör validering och skriv ut kort rapport (till stdout).
    Kastar EnvironmentError om något saknas eller är felaktigt.
    """
    cfg = load_config_from_env()

    # Minimal rapport (inga hemliga värden skrivs ut)
    print("AssertEnv: miljövariabler validerade.")
    print(f" - currencies: {', '.join(cfg.currencies)}")
    print(f" - binance_base_url: {cfg.binance_base_url}")
    print(f" - data_area_root_dir: {cfg.data_area_root_dir}")
    print(f" - currency_history_period: {cfg.currency_history_period}")
    print(f" - currency_history_nof_elements: {cfg.currency_history_nof_elements}")
    print(f" - trade_threshold: {cfg.trade_threshold}")
    print(f" - take_profit_percentage: {cfg.take_profit_percentage}")
    print(f" - stop_loss_percentage: {cfg.stop_loss_percentage}")
    print(f" - dry_run: {cfg.dry_run}")
    print(f" - allowed quote assets: {', '.join(cfg.allowed_quote_assets)}")

    return cfg
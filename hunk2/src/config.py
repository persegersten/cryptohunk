from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Config:
    currencies: List[str]
    binance_secret: str
    binance_key: str
    binance_base_url: str
    binance_currency_history_endpoint: str
    binance_exchange_info_endpoint: str
    binance_my_trades_endpoint: str
    binance_trading_url: str
    dry_run: bool
    data_area_root_dir: str
    currency_history_period: str
    currency_history_nof_elements: int
    trade_threshold: float
    raw_env: dict
    allowed_quote_assets: List[str]
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
    take_profit_percentage: float
    stop_loss_percentage: float
    allowed_quote_assets: List[str]
    ftp_host: Optional[str]
    ftp_dir: Optional[str]
    ftp_username: Optional[str]
    ftp_password: Optional[str]
    ftp_html_regexp: Optional[str]
    raw_env: dict
    ta2_use_ema50_filter: bool = False

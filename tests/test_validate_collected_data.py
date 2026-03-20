#!/usr/bin/env python3
"""
Tester för ValidateCollectedData-modulen.
"""
import unittest
import tempfile
import shutil
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.validate_collected_data import ValidateCollectedData
from src.config import Config


def _make_cfg(tmp_dir: str) -> Config:
    return Config(
        currencies=["BTC", "ETH"],
        binance_secret="test_secret",
        binance_key="test_key",
        binance_base_url="https://api.binance.com",
        binance_currency_history_endpoint="/api/v3/klines",
        binance_exchange_info_endpoint="/api/v3/exchangeInfo",
        binance_my_trades_endpoint="/api/v3/myTrades",
        binance_trading_url="https://api.binance.com/api/v3/order",
        dry_run=True,
        data_area_root_dir=tmp_dir,
        currency_history_period="1h",
        currency_history_nof_elements=300,
        trade_threshold=100.0,
        take_profit_percentage=10.0,
        stop_loss_percentage=6.0,
        allowed_quote_assets=["USDT"],
        ftp_host=None,
        ftp_dir=None,
        ftp_username=None,
        ftp_password=None,
        ftp_html_regexp=None,
        raw_env={},
    )


def _create_full_data(root: Path) -> None:
    """Skapa en komplett mappstruktur med alla nödvändiga filer."""
    (root / "history").mkdir(parents=True, exist_ok=True)
    for cur in ["BTC", "ETH"]:
        (root / "history" / f"{cur}_history.csv").write_text("data")
    (root / "ta").mkdir(parents=True, exist_ok=True)
    for cur in ["BTC", "ETH"]:
        (root / "ta" / f"{cur}_ta.csv").write_text("data")
    (root / "portfolio").mkdir(parents=True, exist_ok=True)
    (root / "portfolio" / "portfolio.json").write_text("{}")
    (root / "trades").mkdir(parents=True, exist_ok=True)
    (root / "trades" / "trades.json").write_text("{}")


class TestCheckTa(unittest.TestCase):
    """Tester för _check_ta-metoden i ValidateCollectedData."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.root = Path(self.test_dir)
        self.cfg = _make_cfg(self.test_dir)
        self.validator = ValidateCollectedData(self.cfg)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_check_ta_ok(self):
        """Exakt 1 TA-fil per valuta ska ge inga fel."""
        (self.root / "ta").mkdir(parents=True, exist_ok=True)
        for cur in ["BTC", "ETH"]:
            (self.root / "ta" / f"{cur}_ta.csv").write_text("data")

        result = self.validator._check_ta()
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["ok"]), 2)

    def test_check_ta_missing_dir(self):
        """Saknad TA-fil för en valuta ska ge fel."""
        # Skapa bara för BTC, inte ETH
        (self.root / "ta").mkdir(parents=True, exist_ok=True)
        (self.root / "ta" / "BTC_ta.csv").write_text("data")

        result = self.validator._check_ta()
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("ETH", result["errors"][0])

    def test_check_ta_empty_dir(self):
        """Tom TA-mapp (inga filer alls) ska ge fel för alla valutor."""
        (self.root / "ta").mkdir(parents=True, exist_ok=True)

        result = self.validator._check_ta()
        self.assertEqual(len(result["errors"]), 2)

    def test_check_ta_multiple_files(self):
        """Exakt en fil per valuta; övriga valutor utan fil ska ge fel."""
        (self.root / "ta").mkdir(parents=True, exist_ok=True)
        (self.root / "ta" / "BTC_ta.csv").write_text("data")
        # ETH saknar fil

        result = self.validator._check_ta()
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("ETH", result["errors"][0])

    def test_check_ta_hidden_files_ignored(self):
        """Dolda filer ska inte räknas som TA-filer; TA-fil ska fortfarande hittas."""
        (self.root / "ta").mkdir(parents=True, exist_ok=True)
        for cur in ["BTC", "ETH"]:
            (self.root / "ta" / f"{cur}_ta.csv").write_text("data")
        (self.root / "ta" / ".hidden").write_text("hidden")

        result = self.validator._check_ta()
        self.assertEqual(result["errors"], [])


class TestRunIncludesTa(unittest.TestCase):
    """Tester för att run() inkluderar TA-validering."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.root = Path(self.test_dir)
        self.cfg = _make_cfg(self.test_dir)
        self.validator = ValidateCollectedData(self.cfg)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_run_fails_when_ta_missing(self):
        """run() ska returnera False om TA-mappen saknas."""
        _create_full_data(self.root)
        # Ta bort ta-mapparna
        shutil.rmtree(self.root / "ta")

        result = self.validator.run()
        self.assertFalse(result)

    def test_run_succeeds_with_all_data(self):
        """run() ska returnera True när alla mappar är korrekta."""
        _create_full_data(self.root)

        result = self.validator.run()
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()

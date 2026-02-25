#!/usr/bin/env python3
"""
Tester för FtpUpload-modulen.
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config
from src.ftp_upload import FtpUpload


def _make_cfg(data_root: str, **overrides) -> Config:
    defaults = dict(
        currencies=["BTC"],
        binance_secret="test_secret",
        binance_key="test_key",
        binance_base_url="https://api.binance.com",
        binance_currency_history_endpoint="/api/v3/klines",
        binance_exchange_info_endpoint="/api/v3/exchangeInfo",
        binance_my_trades_endpoint="/api/v3/myTrades",
        binance_trading_url="https://api.binance.com/api/v3/order",
        dry_run=True,
        data_area_root_dir=data_root,
        currency_history_period="1h",
        currency_history_nof_elements=50,
        trade_threshold=10.0,
        take_profit_percentage=10.0,
        stop_loss_percentage=6.0,
        allowed_quote_assets=["USDT"],
        ftp_host="ftp.example.com",
        ftp_dir="/remote/dir",
        ftp_username="testuser",
        ftp_password="testpass",
        ftp_html_regexp=r".*_chart\.html$",
        raw_env={},
    )
    defaults.update(overrides)
    return Config(**defaults)


def _create_html_files(data_root: Path) -> list:
    """Skapa testfiler under data_root för att simulera genererade HTML-filer."""
    viz_dir = data_root / "visualize"
    viz_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for name in ["BTC_chart.html", "ETH_chart.html", "SOL_chart.html"]:
        f = viz_dir / name
        f.write_text(f"<html><body>{name}</body></html>", encoding="utf-8")
        files.append(f)
    # Skapa en html-fil som inte ska matcha standardmönstret
    other = data_root / "other.html"
    other.write_text("<html><body>other</body></html>", encoding="utf-8")
    return files


class TestFtpUploadFindFiles(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_root = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_find_html_files_matching_pattern(self):
        _create_html_files(self.data_root)
        cfg = _make_cfg(self.test_dir)
        uploader = FtpUpload(cfg)
        files = uploader._find_html_files(r".*_chart\.html$")
        self.assertEqual(len(files), 3)
        names = {f.name for f in files}
        self.assertIn("BTC_chart.html", names)
        self.assertIn("ETH_chart.html", names)
        self.assertIn("SOL_chart.html", names)

    def test_find_html_files_no_match(self):
        _create_html_files(self.data_root)
        cfg = _make_cfg(self.test_dir)
        uploader = FtpUpload(cfg)
        files = uploader._find_html_files(r"nonexistent")
        self.assertEqual(len(files), 0)

    def test_find_html_files_specific_currency(self):
        _create_html_files(self.data_root)
        cfg = _make_cfg(self.test_dir)
        uploader = FtpUpload(cfg)
        files = uploader._find_html_files(r"BTC_chart\.html$")
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, "BTC_chart.html")

    def test_find_html_files_empty_dir(self):
        cfg = _make_cfg(self.test_dir)
        uploader = FtpUpload(cfg)
        files = uploader._find_html_files(r".*\.html$")
        self.assertEqual(len(files), 0)


class TestFtpUploadRun(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_root = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_run_raises_if_ftp_host_missing(self):
        cfg = _make_cfg(self.test_dir, ftp_host=None)
        uploader = FtpUpload(cfg)
        with self.assertRaises(ValueError):
            uploader.run()

    def test_run_raises_if_ftp_username_missing(self):
        cfg = _make_cfg(self.test_dir, ftp_username=None)
        uploader = FtpUpload(cfg)
        with self.assertRaises(ValueError):
            uploader.run()

    def test_run_raises_if_ftp_password_missing(self):
        cfg = _make_cfg(self.test_dir, ftp_password=None)
        uploader = FtpUpload(cfg)
        with self.assertRaises(ValueError):
            uploader.run()

    def test_run_raises_if_ftp_html_regexp_missing(self):
        cfg = _make_cfg(self.test_dir, ftp_html_regexp=None)
        uploader = FtpUpload(cfg)
        with self.assertRaises(ValueError):
            uploader.run()

    def test_run_returns_false_when_no_files_match(self):
        cfg = _make_cfg(self.test_dir, ftp_html_regexp=r"nonexistent")
        uploader = FtpUpload(cfg)
        result = uploader.run()
        self.assertFalse(result)

    @patch("src.ftp_upload.ftplib.FTP")
    def test_run_uploads_matching_files(self, mock_ftp_class):
        _create_html_files(self.data_root)
        cfg = _make_cfg(self.test_dir)

        mock_ftp = MagicMock()
        mock_ftp_class.return_value = mock_ftp

        uploader = FtpUpload(cfg)
        result = uploader.run()

        self.assertTrue(result)
        mock_ftp_class.assert_called_once_with("ftp.example.com")
        mock_ftp.login.assert_called_once_with("testuser", "testpass")
        mock_ftp.cwd.assert_called_once_with("/remote/dir")
        self.assertEqual(mock_ftp.storbinary.call_count, 3)
        mock_ftp.quit.assert_called_once()

    @patch("src.ftp_upload.ftplib.FTP")
    def test_run_skips_cwd_when_ftp_dir_empty(self, mock_ftp_class):
        _create_html_files(self.data_root)
        cfg = _make_cfg(self.test_dir, ftp_dir=None)

        mock_ftp = MagicMock()
        mock_ftp_class.return_value = mock_ftp

        uploader = FtpUpload(cfg)
        result = uploader.run()

        self.assertTrue(result)
        mock_ftp.cwd.assert_not_called()

    @patch("src.ftp_upload.ftplib.FTP")
    def test_run_uploads_correct_filenames(self, mock_ftp_class):
        _create_html_files(self.data_root)
        cfg = _make_cfg(self.test_dir, ftp_html_regexp=r"BTC_chart\.html$")

        mock_ftp = MagicMock()
        mock_ftp_class.return_value = mock_ftp

        uploader = FtpUpload(cfg)
        result = uploader.run()

        self.assertTrue(result)
        self.assertEqual(mock_ftp.storbinary.call_count, 1)
        stor_call = mock_ftp.storbinary.call_args
        self.assertIn("STOR BTC_chart.html", stor_call[0][0])


if __name__ == "__main__":
    unittest.main()

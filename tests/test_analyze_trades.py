#!/usr/bin/env python3
"""
Tests för AnalyzeTrades-modulen.
"""
import unittest
import tempfile
import shutil
import json
import csv
from pathlib import Path
from decimal import Decimal
import sys

# Lägg till projektroten i Python-sökvägen
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analyze_trades import AnalyzeTrades
from src.config import Config


class TestAnalyzeTrades(unittest.TestCase):
    """Tests for AnalyzeTrades class."""

    def setUp(self):
        """Create temporary test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.data_root = Path(self.test_dir)
        
        # Create necessary directories
        self.trades_dir = self.data_root / "trades"
        self.trades_dir.mkdir(parents=True, exist_ok=True)

        # Create mock config
        self.cfg = Config(
            currencies=["BTC", "ETH"],
            binance_secret="test_secret",
            binance_key="test_key",
            binance_base_url="https://api.binance.com",
            binance_currency_history_endpoint="/api/v3/klines",
            binance_exchange_info_endpoint="/api/v3/exchangeInfo",
            binance_my_trades_endpoint="/api/v3/myTrades",
            binance_trading_url="https://api.binance.com/api/v3/order",
            dry_run=True,
            data_area_root_dir=str(self.data_root),
            currency_history_period="1h",
            currency_history_nof_elements=300,
            trade_threshold=0.02,
            take_profit_percentage=10.0,
            stop_loss_percentage=6.0,
            allowed_quote_assets=["USDT"],
            raw_env={}
        )

    def tearDown(self):
        """Clean up temporary test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_trades_file(self, trades: list):
        """Create a trades.json file for testing."""
        trades_file = self.trades_dir / "trades.json"
        with open(trades_file, 'w', encoding='utf-8') as f:
            json.dump(trades, f, indent=2)

    def test_load_trades_missing_file(self):
        """Test att saknad trades.json hanteras korrekt."""
        analyzer = AnalyzeTrades(self.cfg)
        trades = analyzer._load_trades()
        self.assertEqual(trades, [])

    def test_load_trades_invalid_json(self):
        """Test att ogiltig JSON hanteras korrekt."""
        trades_file = self.trades_dir / "trades.json"
        with open(trades_file, 'w', encoding='utf-8') as f:
            f.write("invalid json{")
        
        analyzer = AnalyzeTrades(self.cfg)
        trades = analyzer._load_trades()
        self.assertEqual(trades, [])

    def test_load_trades_not_list(self):
        """Test att JSON som inte är en lista hanteras korrekt."""
        trades_file = self.trades_dir / "trades.json"
        with open(trades_file, 'w', encoding='utf-8') as f:
            json.dump({"not": "a list"}, f)
        
        analyzer = AnalyzeTrades(self.cfg)
        trades = analyzer._load_trades()
        self.assertEqual(trades, [])

    def test_load_trades_valid(self):
        """Test att giltig trades.json laddas korrekt."""
        test_trades = [
            {
                "symbol": "BTCUSDT",
                "id": 1,
                "orderId": 100,
                "price": "50000.00",
                "qty": "0.1",
                "quoteQty": "5000.00",
                "commission": "0.0001",
                "commissionAsset": "BTC",
                "time": 1609459200000,
                "isBuyer": True,
                "isMaker": False,
                "isBestMatch": True
            }
        ]
        self._create_trades_file(test_trades)
        
        analyzer = AnalyzeTrades(self.cfg)
        trades = analyzer._load_trades()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["symbol"], "BTCUSDT")

    def test_trades_summary_by_symbol_generation(self):
        """Test att trades_summary_by_symbol.csv genereras korrekt."""
        test_trades = [
            # Köp 1 BTC för 50000 USDT
            {
                "symbol": "BTCUSDT",
                "price": "50000.00",
                "qty": "1.0",
                "quoteQty": "50000.00",
                "commission": "0.001",
                "commissionAsset": "BTC",
                "time": 1609459200000,
                "isBuyer": True
            },
            # Sälj 0.5 BTC för 55000 USDT
            {
                "symbol": "BTCUSDT",
                "price": "55000.00",
                "qty": "0.5",
                "quoteQty": "27500.00",
                "commission": "27.5",
                "commissionAsset": "USDT",
                "time": 1609459300000,
                "isBuyer": False
            },
            # Köp 10 ETH för 3000 USDT
            {
                "symbol": "ETHUSDT",
                "price": "3000.00",
                "qty": "10.0",
                "quoteQty": "30000.00",
                "commission": "0.01",
                "commissionAsset": "ETH",
                "time": 1609459400000,
                "isBuyer": True
            }
        ]
        self._create_trades_file(test_trades)
        
        analyzer = AnalyzeTrades(self.cfg)
        trades = analyzer._load_trades()
        analyzer._generate_trades_summary_by_symbol(trades)
        
        # Verifiera att filen skapades
        output_file = self.data_root / "output" / "trades_analysis" / "trades_summary_by_symbol.csv"
        self.assertTrue(output_file.exists())
        
        # Läs och verifiera innehållet
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 2)  # 2 symboler
        
        # Hitta BTCUSDT-raden
        btc_row = next(r for r in rows if r['symbol'] == 'BTCUSDT')
        self.assertEqual(btc_row['trades_count'], '2')
        self.assertEqual(Decimal(btc_row['buy_qty_total']), Decimal('1.0'))
        self.assertEqual(Decimal(btc_row['sell_qty_total']), Decimal('0.5'))
        self.assertEqual(Decimal(btc_row['buy_quote_spent_total']), Decimal('50000.00'))
        self.assertEqual(Decimal(btc_row['sell_quote_received_total']), Decimal('27500.00'))
        # Net quote flow = sell - buy = 27500 - 50000 = -22500
        self.assertEqual(Decimal(btc_row['net_quote_flow_before_fee']), Decimal('-22500.00'))
        
        # Hitta ETHUSDT-raden
        eth_row = next(r for r in rows if r['symbol'] == 'ETHUSDT')
        self.assertEqual(eth_row['trades_count'], '1')
        self.assertEqual(Decimal(eth_row['buy_qty_total']), Decimal('10.0'))

    def test_commission_summary_generation(self):
        """Test att commission_summary.csv genereras korrekt."""
        test_trades = [
            {
                "symbol": "BTCUSDT",
                "price": "50000.00",
                "qty": "1.0",
                "quoteQty": "50000.00",
                "commission": "0.001",
                "commissionAsset": "BTC",
                "time": 1609459200000,
                "isBuyer": True
            },
            {
                "symbol": "BTCUSDT",
                "price": "55000.00",
                "qty": "0.5",
                "quoteQty": "27500.00",
                "commission": "27.5",
                "commissionAsset": "USDT",
                "time": 1609459300000,
                "isBuyer": False
            },
            {
                "symbol": "ETHUSDT",
                "price": "3000.00",
                "qty": "10.0",
                "quoteQty": "30000.00",
                "commission": "0.01",
                "commissionAsset": "ETH",
                "time": 1609459400000,
                "isBuyer": True
            },
            {
                "symbol": "BTCUSDT",
                "price": "60000.00",
                "qty": "0.3",
                "quoteQty": "18000.00",
                "commission": "18.0",
                "commissionAsset": "USDT",
                "time": 1609459500000,
                "isBuyer": False
            }
        ]
        self._create_trades_file(test_trades)
        
        analyzer = AnalyzeTrades(self.cfg)
        trades = analyzer._load_trades()
        analyzer._generate_commission_summary(trades)
        
        # Verifiera att filen skapades
        output_file = self.data_root / "output" / "trades_analysis" / "commission_summary.csv"
        self.assertTrue(output_file.exists())
        
        # Läs och verifiera innehållet
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 3)  # 3 olika commission assets
        
        # Verifiera BTC commission
        btc_comm = next(r for r in rows if r['commission_asset'] == 'BTC')
        self.assertEqual(Decimal(btc_comm['commission_total']), Decimal('0.001'))
        self.assertEqual(btc_comm['trades_count'], '1')
        
        # Verifiera USDT commission (2 trades)
        usdt_comm = next(r for r in rows if r['commission_asset'] == 'USDT')
        self.assertEqual(Decimal(usdt_comm['commission_total']), Decimal('45.5'))  # 27.5 + 18.0
        self.assertEqual(usdt_comm['trades_count'], '2')
        
        # Verifiera ETH commission
        eth_comm = next(r for r in rows if r['commission_asset'] == 'ETH')
        self.assertEqual(Decimal(eth_comm['commission_total']), Decimal('0.01'))
        self.assertEqual(eth_comm['trades_count'], '1')

    def test_realized_pnl_fifo_basic(self):
        """Test FIFO PnL-beräkning med enkel buy-sell-sekvens."""
        test_trades = [
            # Köp 1 BTC för 50000 USDT
            {
                "symbol": "BTCUSDT",
                "price": "50000.00",
                "qty": "1.0",
                "quoteQty": "50000.00",
                "commission": "50.0",
                "commissionAsset": "USDT",
                "time": 1609459200000,
                "isBuyer": True
            },
            # Sälj 1 BTC för 55000 USDT
            {
                "symbol": "BTCUSDT",
                "price": "55000.00",
                "qty": "1.0",
                "quoteQty": "55000.00",
                "commission": "55.0",
                "commissionAsset": "USDT",
                "time": 1609459300000,
                "isBuyer": False
            }
        ]
        self._create_trades_file(test_trades)
        
        analyzer = AnalyzeTrades(self.cfg)
        trades = analyzer._load_trades()
        analyzer._generate_realized_pnl_fifo(trades)
        
        # Verifiera att filen skapades
        output_file = self.data_root / "output" / "trades_analysis" / "realized_pnl_fifo_by_symbol.csv"
        self.assertTrue(output_file.exists())
        
        # Läs och verifiera innehållet
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 1)
        btc_row = rows[0]
        self.assertEqual(btc_row['symbol'], 'BTCUSDT')
        
        # PnL = (55000 - 50000) - commission = 5000 - 105 = 4895
        # Men commission dras endast om den är i quote asset
        # Gross PnL = 5000, commission = 105 USDT
        expected_pnl = Decimal('5000') - Decimal('105')  # 4895
        self.assertEqual(Decimal(btc_row['realized_pnl_quote']), expected_pnl)
        self.assertEqual(Decimal(btc_row['matched_sell_qty']), Decimal('1.0'))
        self.assertEqual(Decimal(btc_row['avg_buy_price']), Decimal('50000.00'))
        self.assertEqual(Decimal(btc_row['avg_sell_price']), Decimal('55000.00'))

    def test_realized_pnl_fifo_multiple_buys(self):
        """Test FIFO PnL med flera köp och en försäljning."""
        test_trades = [
            # Köp 1 BTC för 50000 USDT
            {
                "symbol": "BTCUSDT",
                "price": "50000.00",
                "qty": "1.0",
                "quoteQty": "50000.00",
                "commission": "0.001",
                "commissionAsset": "BTC",
                "time": 1609459200000,
                "isBuyer": True
            },
            # Köp 1 BTC för 52000 USDT
            {
                "symbol": "BTCUSDT",
                "price": "52000.00",
                "qty": "1.0",
                "quoteQty": "52000.00",
                "commission": "0.001",
                "commissionAsset": "BTC",
                "time": 1609459250000,
                "isBuyer": True
            },
            # Sälj 1.5 BTC för 55000 USDT (matchar första köpet helt och hälften av andra)
            {
                "symbol": "BTCUSDT",
                "price": "55000.00",
                "qty": "1.5",
                "quoteQty": "82500.00",
                "commission": "82.5",
                "commissionAsset": "USDT",
                "time": 1609459300000,
                "isBuyer": False
            }
        ]
        self._create_trades_file(test_trades)
        
        analyzer = AnalyzeTrades(self.cfg)
        trades = analyzer._load_trades()
        analyzer._generate_realized_pnl_fifo(trades)
        
        # Verifiera att filen skapades
        output_file = self.data_root / "output" / "trades_analysis" / "realized_pnl_fifo_by_symbol.csv"
        self.assertTrue(output_file.exists())
        
        # Läs och verifiera innehållet
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 1)
        btc_row = rows[0]
        
        # FIFO matching:
        # 1. Matcha 1 BTC från första köpet (50000) mot försäljning (55000) = +5000
        # 2. Matcha 0.5 BTC från andra köpet (52000) mot försäljning (55000) = +1500
        # Total PnL = 5000 + 1500 = 6500
        # Commission = 82.5 USDT (subtraheras eftersom den är i quote asset)
        # Net PnL = 6500 - 82.5 = 6417.5
        expected_pnl = Decimal('6500') - Decimal('82.5')
        self.assertEqual(Decimal(btc_row['realized_pnl_quote']), expected_pnl)
        self.assertEqual(Decimal(btc_row['matched_sell_qty']), Decimal('1.5'))
        
        # Avg buy price = (1 * 50000 + 0.5 * 52000) / 1.5 = 76000 / 1.5 = 50666.666...
        avg_buy = (Decimal('50000') + Decimal('26000')) / Decimal('1.5')
        self.assertAlmostEqual(float(btc_row['avg_buy_price']), float(avg_buy), places=2)

    def test_realized_pnl_fifo_unmatched_sell(self):
        """Test FIFO PnL när försäljning överskrider köp (unmatched sell)."""
        test_trades = [
            # Köp 1 BTC för 50000 USDT
            {
                "symbol": "BTCUSDT",
                "price": "50000.00",
                "qty": "1.0",
                "quoteQty": "50000.00",
                "commission": "0.001",
                "commissionAsset": "BTC",
                "time": 1609459200000,
                "isBuyer": True
            },
            # Sälj 1.5 BTC (endast 1 BTC kan matchas)
            {
                "symbol": "BTCUSDT",
                "price": "55000.00",
                "qty": "1.5",
                "quoteQty": "82500.00",
                "commission": "82.5",
                "commissionAsset": "USDT",
                "time": 1609459300000,
                "isBuyer": False
            }
        ]
        self._create_trades_file(test_trades)
        
        analyzer = AnalyzeTrades(self.cfg)
        trades = analyzer._load_trades()
        analyzer._generate_realized_pnl_fifo(trades)
        
        # Verifiera att filen skapades
        output_file = self.data_root / "output" / "trades_analysis" / "realized_pnl_fifo_by_symbol.csv"
        self.assertTrue(output_file.exists())
        
        # Läs och verifiera innehållet
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 1)
        btc_row = rows[0]
        
        # Endast 1 BTC matchas, PnL = 5000 - 82.5 = 4917.5
        self.assertEqual(Decimal(btc_row['matched_sell_qty']), Decimal('1.0'))
        self.assertIn('Unmatched sell', btc_row['notes'])

    def test_realized_pnl_fifo_unmatched_buy(self):
        """Test FIFO PnL när köp överskrider försäljning (unmatched buy)."""
        test_trades = [
            # Köp 2 BTC för 50000 USDT
            {
                "symbol": "BTCUSDT",
                "price": "50000.00",
                "qty": "2.0",
                "quoteQty": "100000.00",
                "commission": "0.002",
                "commissionAsset": "BTC",
                "time": 1609459200000,
                "isBuyer": True
            },
            # Sälj 1 BTC
            {
                "symbol": "BTCUSDT",
                "price": "55000.00",
                "qty": "1.0",
                "quoteQty": "55000.00",
                "commission": "55.0",
                "commissionAsset": "USDT",
                "time": 1609459300000,
                "isBuyer": False
            }
        ]
        self._create_trades_file(test_trades)
        
        analyzer = AnalyzeTrades(self.cfg)
        trades = analyzer._load_trades()
        analyzer._generate_realized_pnl_fifo(trades)
        
        # Verifiera att filen skapades
        output_file = self.data_root / "output" / "trades_analysis" / "realized_pnl_fifo_by_symbol.csv"
        self.assertTrue(output_file.exists())
        
        # Läs och verifiera innehållet
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 1)
        btc_row = rows[0]
        
        # Endast 1 BTC matchas, PnL = 5000 - 55 = 4945
        self.assertEqual(Decimal(btc_row['matched_sell_qty']), Decimal('1.0'))
        self.assertIn('Unmatched buy', btc_row['notes'])

    def test_full_run_with_valid_data(self):
        """Test fullständig körning med giltig data."""
        test_trades = [
            {
                "symbol": "BTCUSDT",
                "price": "50000.00",
                "qty": "1.0",
                "quoteQty": "50000.00",
                "commission": "0.001",
                "commissionAsset": "BTC",
                "time": 1609459200000,
                "isBuyer": True
            },
            {
                "symbol": "BTCUSDT",
                "price": "55000.00",
                "qty": "1.0",
                "quoteQty": "55000.00",
                "commission": "55.0",
                "commissionAsset": "USDT",
                "time": 1609459300000,
                "isBuyer": False
            }
        ]
        self._create_trades_file(test_trades)
        
        analyzer = AnalyzeTrades(self.cfg)
        success = analyzer.run()
        
        self.assertTrue(success)
        
        # Verifiera att alla filer skapades
        output_root = self.data_root / "output" / "trades_analysis"
        self.assertTrue((output_root / "trades_summary_by_symbol.csv").exists())
        self.assertTrue((output_root / "commission_summary.csv").exists())
        self.assertTrue((output_root / "realized_pnl_fifo_by_symbol.csv").exists())

    def test_full_run_with_missing_file(self):
        """Test fullständig körning utan trades.json."""
        analyzer = AnalyzeTrades(self.cfg)
        success = analyzer.run()
        
        # Ska returnera False men inte krascha
        self.assertFalse(success)

    def test_extract_quote_asset(self):
        """Test extrahering av quote asset från symbol."""
        analyzer = AnalyzeTrades(self.cfg)
        
        self.assertEqual(analyzer._extract_quote_asset("BTCUSDT"), "USDT")
        self.assertEqual(analyzer._extract_quote_asset("ETHBTC"), "BTC")
        self.assertEqual(analyzer._extract_quote_asset("BNBUSDC"), "USDC")
        self.assertEqual(analyzer._extract_quote_asset("ADAETH"), "ETH")
        self.assertIsNone(analyzer._extract_quote_asset("UNKNOWNSYMBOL"))

    def test_daily_trades_generation(self):
        """Test att daily_trades.csv genereras korrekt."""
        test_trades = [
            # Köp 1 BTC för 50000 USDT den 2021-01-01
            {
                "symbol": "BTCUSDT",
                "price": "50000.00",
                "qty": "1.0",
                "quoteQty": "50000.00",
                "commission": "0.001",
                "commissionAsset": "BTC",
                "time": 1609459200000,  # 2021-01-01
                "isBuyer": True
            },
            # Sälj 1 BTC för 55000 USDT den 2021-01-02
            {
                "symbol": "BTCUSDT",
                "price": "55000.00",
                "qty": "1.0",
                "quoteQty": "55000.00",
                "commission": "55.0",
                "commissionAsset": "USDT",
                "time": 1609545600000,  # 2021-01-02
                "isBuyer": False
            },
            # Köp 10 ETH för 3000 USDT den 2021-01-03
            {
                "symbol": "ETHUSDT",
                "price": "3000.00",
                "qty": "10.0",
                "quoteQty": "30000.00",
                "commission": "0.01",
                "commissionAsset": "ETH",
                "time": 1609632000000,  # 2021-01-03
                "isBuyer": True
            },
            # Sälj 5 ETH för 3200 USDT den 2021-01-04
            {
                "symbol": "ETHUSDT",
                "price": "3200.00",
                "qty": "5.0",
                "quoteQty": "16000.00",
                "commission": "16.0",
                "commissionAsset": "USDT",
                "time": 1609718400000,  # 2021-01-04
                "isBuyer": False
            }
        ]
        self._create_trades_file(test_trades)
        
        analyzer = AnalyzeTrades(self.cfg)
        trades = analyzer._load_trades()
        analyzer._generate_daily_trades_summary(trades)
        
        # Verifiera att filen skapades
        output_file = self.data_root / "output" / "trades_analysis" / "daily_trades.csv"
        self.assertTrue(output_file.exists())
        
        # Läs och verifiera innehållet
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 4)
        
        # Verifiera första köpet (BTC)
        btc_buy = rows[0]
        self.assertEqual(btc_buy['datum'], '2021-01-01')
        self.assertEqual(btc_buy['valuta'], 'BTC')
        self.assertEqual(btc_buy['action'], 'BUY')
        self.assertEqual(Decimal(btc_buy['amount']), Decimal('1.0'))
        self.assertEqual(Decimal(btc_buy['amount_usdc']), Decimal('50000.00'))
        self.assertEqual(btc_buy['percent_change'], 'n/a')
        self.assertEqual(btc_buy['value_change_usdc'], 'n/a')
        
        # Verifiera BTC försäljningen
        btc_sell = rows[1]
        self.assertEqual(btc_sell['datum'], '2021-01-02')
        self.assertEqual(btc_sell['valuta'], 'BTC')
        self.assertEqual(btc_sell['action'], 'SELL')
        self.assertEqual(Decimal(btc_sell['amount']), Decimal('1.0'))
        self.assertEqual(Decimal(btc_sell['amount_usdc']), Decimal('55000.00'))
        # Procent: (55000 - 50000) / 50000 * 100 = 10%
        self.assertEqual(btc_sell['percent_change'], '10.00%')
        # Värde: 55000 - 50000 = 5000
        self.assertEqual(Decimal(btc_sell['value_change_usdc']), Decimal('5000.000'))
        
        # Verifiera ETH köpet
        eth_buy = rows[2]
        self.assertEqual(eth_buy['datum'], '2021-01-03')
        self.assertEqual(eth_buy['valuta'], 'ETH')
        self.assertEqual(eth_buy['action'], 'BUY')
        
        # Verifiera ETH försäljningen
        eth_sell = rows[3]
        self.assertEqual(eth_sell['datum'], '2021-01-04')
        self.assertEqual(eth_sell['valuta'], 'ETH')
        self.assertEqual(eth_sell['action'], 'SELL')
        self.assertEqual(Decimal(eth_sell['amount']), Decimal('5.0'))
        # Procent: (3200 - 3000) / 3000 * 100 = 6.67%
        self.assertEqual(eth_sell['percent_change'], '6.67%')
        # Värde: 5 * 3200 - 5 * 3000 = 16000 - 15000 = 1000
        self.assertEqual(Decimal(eth_sell['value_change_usdc']), Decimal('1000.000'))

    def test_daily_trades_with_commission_conversion(self):
        """Test att provisioner konverteras korrekt till USDC."""
        test_trades = [
            {
                "symbol": "BTCUSDT",
                "price": "50000.00",
                "qty": "0.1",
                "quoteQty": "5000.00",
                "commission": "0.0001",
                "commissionAsset": "BTC",  # Commission i BTC ska konverteras
                "time": 1609459200000,
                "isBuyer": True
            }
        ]
        self._create_trades_file(test_trades)
        
        analyzer = AnalyzeTrades(self.cfg)
        trades = analyzer._load_trades()
        analyzer._generate_daily_trades_summary(trades)
        
        output_file = self.data_root / "output" / "trades_analysis" / "daily_trades.csv"
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 1)
        row = rows[0]
        
        # Commission i BTC: 0.0001 * 50000 = 5 USDT
        self.assertEqual(Decimal(row['commission_usdc']), Decimal('5.00000'))

    def test_full_run_includes_daily_trades(self):
        """Test att daily_trades.csv skapas vid fullständig körning."""
        test_trades = [
            {
                "symbol": "BTCUSDT",
                "price": "50000.00",
                "qty": "1.0",
                "quoteQty": "50000.00",
                "commission": "0.001",
                "commissionAsset": "BTC",
                "time": 1609459200000,
                "isBuyer": True
            }
        ]
        self._create_trades_file(test_trades)
        
        analyzer = AnalyzeTrades(self.cfg)
        success = analyzer.run()
        
        self.assertTrue(success)
        
        # Verifiera att daily_trades.csv skapades
        output_root = self.data_root / "output" / "trades_analysis"
        self.assertTrue((output_root / "daily_trades.csv").exists())


if __name__ == "__main__":
    unittest.main()

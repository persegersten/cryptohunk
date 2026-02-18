#!/usr/bin/env python3
"""
AnalyzeTrades - Analyze trade history from Binance.

This module:
1. Reads trades from DATA_AREA_ROOT_DIR/trades/trades.json
2. Produces analysis CSVs in DATA_AREA_ROOT_DIR/output/trades_analysis/
   - trades_summary_by_symbol.csv
   - commission_summary.csv
   - realized_pnl_fifo_by_symbol.csv (optional, when FIFO is possible)
"""
import logging
import json
import csv
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict
from decimal import Decimal

from .config import Config

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class AnalyzeTrades:
    """Analysera handelshistorik från Binance."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.data_root = Path(cfg.data_area_root_dir)
        self.trades_file = self.data_root / "trades" / "trades.json"
        self.output_root = self.data_root / "output" / "trades_analysis"

    def _ensure_dir(self, path: Path) -> None:
        """Skapa katalog om den inte finns."""
        path.mkdir(parents=True, exist_ok=True)

    def _load_trades(self) -> List[Dict[str, Any]]:
        """
        Ladda trades från trades.json.
        Returnerar tom lista om filen saknas eller är ogiltig.
        """
        if not self.trades_file.exists():
            log.warning("Trades-fil saknas: %s", self.trades_file)
            return []

        try:
            with open(self.trades_file, "r", encoding="utf-8") as fh:
                trades = json.load(fh)
            
            if not isinstance(trades, list):
                log.error("Trades-fil innehåller inte en lista: %s", self.trades_file)
                return []
            
            log.info("Laddade %d trades från %s", len(trades), self.trades_file)
            return trades
        
        except json.JSONDecodeError as e:
            log.error("JSON-fel vid läsning av trades: %s", e)
            return []
        except Exception as e:
            log.error("Oväntat fel vid läsning av trades: %s", e)
            return []

    def _generate_trades_summary_by_symbol(self, trades: List[Dict[str, Any]]) -> None:
        """
        Genererar trades_summary_by_symbol.csv med aggregerad information per symbol.
        
        Binance myTrades format:
        - symbol: trading pair (e.g., "BTCUSDT")
        - isBuyer: boolean, true if buyer
        - qty: quantity traded (base asset)
        - price: price per unit
        - quoteQty: quote quantity (qty * price)
        - commission: fee amount
        - commissionAsset: asset in which fee is paid
        """
        summary = defaultdict(lambda: {
            'trades_count': 0,
            'buy_qty_total': Decimal('0'),
            'sell_qty_total': Decimal('0'),
            'buy_quote_spent_total': Decimal('0'),
            'sell_quote_received_total': Decimal('0'),
            'commissions': defaultdict(Decimal)
        })

        for trade in trades:
            try:
                symbol = trade.get('symbol', 'UNKNOWN')
                is_buyer = trade.get('isBuyer', False)
                qty = Decimal(str(trade.get('qty', 0)))
                quote_qty = Decimal(str(trade.get('quoteQty', 0)))
                commission = Decimal(str(trade.get('commission', 0)))
                commission_asset = trade.get('commissionAsset', 'UNKNOWN')

                s = summary[symbol]
                s['trades_count'] += 1

                if is_buyer:
                    s['buy_qty_total'] += qty
                    s['buy_quote_spent_total'] += quote_qty
                else:
                    s['sell_qty_total'] += qty
                    s['sell_quote_received_total'] += quote_qty

                if commission > 0:
                    s['commissions'][commission_asset] += commission

            except (KeyError, ValueError, TypeError) as e:
                log.warning("Felaktig trade-post ignorerad: %s", e)
                continue

        # Skriv CSV
        output_file = self.output_root / "trades_summary_by_symbol.csv"
        self._ensure_dir(self.output_root)

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = [
                'symbol',
                'trades_count',
                'buy_qty_total',
                'sell_qty_total',
                'buy_quote_spent_total',
                'sell_quote_received_total',
                'net_quote_flow_before_fee',
                'commission_assets',
                'commission_total_original'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for symbol in sorted(summary.keys()):
                s = summary[symbol]
                net_quote_flow = s['sell_quote_received_total'] - s['buy_quote_spent_total']
                
                # Format commission information
                commission_assets = ', '.join(sorted(s['commissions'].keys()))
                commission_totals = ', '.join(
                    f"{asset}:{amount}" for asset, amount in sorted(s['commissions'].items())
                )

                writer.writerow({
                    'symbol': symbol,
                    'trades_count': s['trades_count'],
                    'buy_qty_total': str(s['buy_qty_total']),
                    'sell_qty_total': str(s['sell_qty_total']),
                    'buy_quote_spent_total': str(s['buy_quote_spent_total']),
                    'sell_quote_received_total': str(s['sell_quote_received_total']),
                    'net_quote_flow_before_fee': str(net_quote_flow),
                    'commission_assets': commission_assets,
                    'commission_total_original': commission_totals
                })

        log.info("Sparade trades_summary_by_symbol.csv: %s", output_file)

    def _generate_commission_summary(self, trades: List[Dict[str, Any]]) -> None:
        """
        Genererar commission_summary.csv med total provision per asset.
        """
        commission_summary = defaultdict(lambda: {
            'commission_total': Decimal('0'),
            'trades_count': 0
        })

        for trade in trades:
            try:
                commission = Decimal(str(trade.get('commission', 0)))
                commission_asset = trade.get('commissionAsset', 'UNKNOWN')

                if commission > 0:
                    commission_summary[commission_asset]['commission_total'] += commission
                    commission_summary[commission_asset]['trades_count'] += 1

            except (ValueError, TypeError) as e:
                log.warning("Felaktig commission-data ignorerad: %s", e)
                continue

        # Skriv CSV
        output_file = self.output_root / "commission_summary.csv"
        self._ensure_dir(self.output_root)

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['commission_asset', 'commission_total', 'trades_count']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for asset in sorted(commission_summary.keys()):
                cs = commission_summary[asset]
                writer.writerow({
                    'commission_asset': asset,
                    'commission_total': str(cs['commission_total']),
                    'trades_count': cs['trades_count']
                })

        log.info("Sparade commission_summary.csv: %s", output_file)

    def _generate_realized_pnl_fifo(self, trades: List[Dict[str, Any]]) -> None:
        """
        Implementera FIFO (First-In-First-Out) matching för att beräkna realiserad PnL.
        
        För varje symbol:
        - Köp skapar inventory (FIFO-kö)
        - Sälj matchar mot äldsta köp
        - Beräkna PnL per matchad försäljning
        """
        # Gruppera trades per symbol
        trades_by_symbol = defaultdict(list)
        for trade in trades:
            symbol = trade.get('symbol')
            if symbol:
                trades_by_symbol[symbol].append(trade)

        # Sortera trades per symbol baserat på tid
        for symbol in trades_by_symbol:
            trades_by_symbol[symbol].sort(key=lambda t: t.get('time', 0))

        # Beräkna FIFO PnL per symbol
        pnl_results = []

        for symbol, symbol_trades in trades_by_symbol.items():
            buy_queue = []  # FIFO-kö: [(qty, price, commission, commission_asset)]
            realized_pnl = Decimal('0')
            matched_sell_qty = Decimal('0')
            total_buy_cost = Decimal('0')
            total_sell_revenue = Decimal('0')
            commissions = defaultdict(Decimal)
            quote_asset = self._extract_quote_asset(symbol)
            notes = []

            for trade in symbol_trades:
                try:
                    is_buyer = trade.get('isBuyer', False)
                    qty = Decimal(str(trade.get('qty', 0)))
                    price = Decimal(str(trade.get('price', 0)))
                    commission = Decimal(str(trade.get('commission', 0)))
                    commission_asset = trade.get('commissionAsset', 'UNKNOWN')

                    # Samla alla commissions
                    if commission > 0:
                        commissions[commission_asset] += commission

                    if is_buyer:
                        # Köp: lägg till i FIFO-kö
                        buy_queue.append((qty, price))
                    else:
                        # Sälj: matcha mot äldsta köp
                        remaining_sell_qty = qty
                        sell_revenue = qty * price

                        while remaining_sell_qty > 0 and buy_queue:
                            buy_qty, buy_price = buy_queue[0]

                            if buy_qty <= remaining_sell_qty:
                                # Hela köpet matchas
                                matched_qty = buy_qty
                                buy_queue.pop(0)
                            else:
                                # Delvis matchning av köp
                                matched_qty = remaining_sell_qty
                                buy_queue[0] = (buy_qty - matched_qty, buy_price)

                            # Beräkna PnL för matchad del
                            buy_cost = matched_qty * buy_price
                            sell_value = matched_qty * price
                            pnl = sell_value - buy_cost

                            realized_pnl += pnl
                            matched_sell_qty += matched_qty
                            total_buy_cost += buy_cost
                            total_sell_revenue += sell_value
                            remaining_sell_qty -= matched_qty

                        if remaining_sell_qty > 0:
                            notes.append(f"Unmatched sell: {remaining_sell_qty}")

                except (ValueError, TypeError) as e:
                    log.warning("Felaktig trade vid FIFO-beräkning: %s", e)
                    continue

            if buy_queue:
                unmatched_qty = sum(q for q, _ in buy_queue)
                notes.append(f"Unmatched buy: {unmatched_qty}")

            # Beräkna genomsnittspriser
            avg_buy_price = total_buy_cost / matched_sell_qty if matched_sell_qty > 0 else Decimal('0')
            avg_sell_price = total_sell_revenue / matched_sell_qty if matched_sell_qty > 0 else Decimal('0')

            # Justera PnL om commission är i quote asset
            gross_pnl = realized_pnl
            if quote_asset and quote_asset in commissions:
                # Subtrahera commission från PnL om den är i quote asset
                net_pnl = gross_pnl - commissions[quote_asset]
                notes.append(f"Commission in {quote_asset} subtracted from PnL")
            else:
                net_pnl = gross_pnl
                if commissions:
                    fee_assets = ', '.join(commissions.keys())
                    notes.append(f"Fees in {fee_assets} not converted")

            pnl_results.append({
                'symbol': symbol,
                'realized_pnl_quote': str(net_pnl),
                'matched_sell_qty': str(matched_sell_qty),
                'avg_buy_price': str(avg_buy_price),
                'avg_sell_price': str(avg_sell_price),
                'notes': '; '.join(notes) if notes else ''
            })

        # Skriv CSV
        output_file = self.output_root / "realized_pnl_fifo_by_symbol.csv"
        self._ensure_dir(self.output_root)

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = [
                'symbol',
                'realized_pnl_quote',
                'matched_sell_qty',
                'avg_buy_price',
                'avg_sell_price',
                'notes'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(pnl_results)

        log.info("Sparade realized_pnl_fifo_by_symbol.csv: %s", output_file)

    def _extract_quote_asset(self, symbol: str) -> Optional[str]:
        """
        Försök extrahera quote asset från symbol.
        Ex: BTCUSDT -> USDT, ETHBTC -> BTC
        """
        # Vanliga quote assets på Binance
        common_quotes = ['USDT', 'USDC', 'BUSD', 'BTC', 'ETH', 'BNB', 'EUR', 'GBP']
        
        for quote in common_quotes:
            if symbol.endswith(quote):
                return quote
        
        return None

    def run(self) -> bool:
        """
        Huvudmetod för att köra trade-analys.
        Returnerar True vid framgång, False vid fel.
        """
        log.info("=== Startar AnalyzeTrades ===")

        trades = self._load_trades()
        if not trades:
            log.warning("Inga trades att analysera.")
            return False

        try:
            self._generate_trades_summary_by_symbol(trades)
            self._generate_commission_summary(trades)
            self._generate_realized_pnl_fifo(trades)
            log.info("AnalyzeTrades avslutad framgångsrikt!")
            return True
        except Exception as e:
            log.error("Kritiskt fel i AnalyzeTrades: %s", e)
            return False


def analyze_trades_main(cfg: Config) -> None:
    """
    Main entry point för trade-analys.
    Anropas från main.py när --analyze-trades flaggan sätts.
    Kastar SystemExit(1) vid fel.
    """
    analyzer = AnalyzeTrades(cfg)
    success = analyzer.run()
    if not success:
        log.error("AnalyzeTrades misslyckades")
        raise SystemExit(1)


if __name__ == "__main__":
    """
    Kör från kommandoraden. Hämtar env via assert_env_and_report() för att få Config.
    Ex:
      python3 src/analyze_trades.py
    """
    from .assert_env import assert_env_and_report
    
    try:
        cfg = assert_env_and_report()
    except Exception as e:
        log.error("Konfig kunde inte laddas: %s", e)
        raise SystemExit(2)

    success = AnalyzeTrades(cfg).run()
    raise SystemExit(0 if success else 1)

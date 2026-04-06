#!/usr/bin/env python3
"""
VisualizeHistory - Generera interaktivt kurshistorikdiagram med köp/säljmarkeringar.

Läser kurshistorik från DATA_AREA_ROOT_DIR/history/<currency>_history.csv
och tradehistorik från DATA_AREA_ROOT_DIR/trades/trades.json.

Genererar ett interaktivt HTML-dokument med alla valutor och en dropdown-meny för
att välja vilken valuta som visas. Varje valutadiagram innehåller:
- Stearinljusdiagram (candlestick) för kurshistorik
- Gröna pilar uppåt (▲) för köp
- Röda pilar nedåt (▼) för sälj
- Klick på köp/sälj-symbol visar detaljerad handelsinformation

Sparar resultaten i DATA_AREA_ROOT_DIR/visualize/history_chart.html
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
from plotly.subplots import make_subplots

from .config import Config

log = logging.getLogger(__name__)


class VisualizeHistory:
    """Generera interaktiva kurshistorikdiagram med köp/säljmarkeringar."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.data_root = Path(cfg.data_area_root_dir)
        self.history_root = self.data_root / "history"
        self.trades_file = self.data_root / "trades" / "trades.json"
        self.output_dir = self.data_root / "visualize"

    def _ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def _read_backtest(self, currency: str) -> Optional[pd.DataFrame]:
        """Läs backtestresultat för angiven valuta.

        Returnerar DataFrame med kolumnerna 'datetime' och 'signal' (BUY/SELL/HOLD),
        sorterade på datetime. Returnerar None om filen saknas eller inte kan läsas.
        """
        backtest_file = self.data_root / "output" / "backtesting" / f"{currency}_backtesting.csv"
        if not backtest_file.exists():
            log.info("Backtestfil saknas för %s: %s", currency, backtest_file)
            return None
        try:
            df = pd.read_csv(backtest_file)
            if "timestamp_ms" not in df.columns or "signal" not in df.columns:
                log.warning("Backtestfil för %s saknar förväntade kolumner", currency)
                return None
            df["timestamp_ms"] = pd.to_numeric(df["timestamp_ms"], errors="coerce")
            df = df.dropna(subset=["timestamp_ms"])
            if df.empty:
                return None
            df["datetime"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
            df = df.sort_values("datetime").reset_index(drop=True)
            log.info("Läste backtestdata för %s: %d rader", currency, len(df))
            return df
        except Exception as e:
            log.error("Fel vid läsning av backtestdata för %s: %s", currency, e)
            return None

    def _read_history(self, currency: str) -> Optional[pd.DataFrame]:
        """Läs kurshistorik för angiven valuta."""
        csv_file = self.history_root / f"{currency}_history.csv"
        if not csv_file.exists():
            log.warning("Historikfil saknas för %s: %s", currency, csv_file)
            return None
        try:
            df = pd.read_csv(csv_file)
            df["datetime"] = pd.to_datetime(df["Open_Time_ms"], unit="ms", utc=True)
            log.info("Läste kurshistorik för %s: %d rader", currency, len(df))
            return df
        except Exception as e:
            log.error("Fel vid läsning av kurshistorik för %s: %s", currency, e)
            return None

    def _read_trades(self) -> List[Dict[str, Any]]:
        """Läs tradehistorik från JSON-fil."""
        if not self.trades_file.exists():
            log.info("Tradehistorikfil saknas: %s", self.trades_file)
            return []
        try:
            with open(self.trades_file, "r", encoding="utf-8") as f:
                trades = json.load(f)
            if not isinstance(trades, list):
                log.warning("Oväntat format på tradehistorik")
                return []
            log.info("Läste %d trades från %s", len(trades), self.trades_file)
            return trades
        except Exception as e:
            log.error("Fel vid läsning av tradehistorik: %s", e)
            return []

    def _filter_trades_for_currency(
        self, trades: List[Dict[str, Any]], currency: str
    ) -> List[Dict[str, Any]]:
        """Filtrera trades för angiven valuta (base asset)."""
        currency_upper = currency.upper()
        return [
            t for t in trades
            if str(t.get("symbol", "")).upper().startswith(currency_upper)
        ]

    def _format_trade_label(
        self, trade: Dict[str, Any], buy_price: Optional[float] = None
    ) -> str:
        """Skapa en detaljerad textetikett för ett trade."""
        is_buyer = trade.get("isBuyer", False)
        action = "KÖP" if is_buyer else "SÄLJ"
        symbol = trade.get("symbol", "?")
        price = trade.get("price", "?")
        qty = trade.get("qty", "?")
        quote_qty = trade.get("quoteQty", "?")
        commission = trade.get("commission", "?")
        commission_asset = trade.get("commissionAsset", "?")
        trade_time_ms = trade.get("time")
        if trade_time_ms:
            dt = datetime.fromtimestamp(trade_time_ms / 1000, tz=timezone.utc)
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            time_str = "?"

        label = (
            f"<b>{action}</b><br>"
            f"Symbol: {symbol}<br>"
            f"Pris: {price}<br>"
            f"Mängd: {qty}<br>"
            f"Totalt (quote): {quote_qty}<br>"
            f"Avgift: {commission} {commission_asset}<br>"
            f"Tid: {time_str}"
        )

        if not is_buyer and buy_price is not None and buy_price > 0:
            try:
                sell_price = float(price)
                pct_change = (sell_price - buy_price) / buy_price * 100
                sign = "+" if pct_change >= 0 else ""
                label += f"<br>Förändring vs. köp: {sign}{pct_change:.2f}%"
            except (ValueError, TypeError):
                pass

        return label

    @staticmethod
    def _reconstruct_balance_history(
        current_balance: float,
        trade_events: List[tuple],
        idx: pd.DatetimeIndex,
    ) -> pd.Series:
        """
        Rekonstruera balanshistorik bakåt från aktuellt saldo.

        Startar från current_balance (känt korrekt värde från portfolio.json) och
        går bakåt i tid – varje candles nettoflöde "ångras" för att ge balansen vid
        slutet av den föregående candle'n.

        Trades binnas till sin timkandle via floor('h'), så en affär kl. 20:15
        tillhör 20:00-candle'n och visas som en förändring i den candle'n.

        Returnerar en Series med stigande tidsindex som matchar idx.
        """
        # Bin varje affär till sin timkandle
        hourly_flow: Dict[pd.Timestamp, float] = {}
        for ts, delta in trade_events:
            candle = ts.floor("h")
            hourly_flow[candle] = hourly_flow.get(candle, 0.0) + delta

        # Dra av flöden från affärer som inträffade EFTER sista candle'n i fönstret
        # (dessa finns i trades.json men utanför vår 7-dagarsperiod).
        if len(idx) > 0:
            last_candle = idx[-1]
            post_window_flow = sum(
                v for k, v in hourly_flow.items() if k > last_candle
            )
        else:
            post_window_flow = 0.0

        # Gå bakåt genom alla candles och rekonstruera saldo
        balances: Dict[pd.Timestamp, float] = {}
        running_balance = current_balance - post_window_flow
        for candle_time in reversed(idx):
            # Saldo vid slutet av denna candle (efter affärer som skedde under candle'n)
            balances[candle_time] = running_balance
            # Ångra affärerna i denna candle för att få saldo vid slutet av föregående candle
            running_balance -= hourly_flow.get(candle_time, 0.0)

        return pd.Series(balances, index=idx)

    def _write_debug_csv(
        self,
        trades: List[Dict[str, Any]],
        dfs: Dict[str, pd.DataFrame],
    ) -> None:
        """
        Skriv en debug-CSV med per-valuta-innehav och USDC-värden för senaste veckan.

        Kolumner:
          datetime,
          <valuta> för varje valuta i dfs och USDC – alla rekonstruerade bakåt från
          aktuellt saldo i portfolio.json via _reconstruct_balance_history,
          <valuta>USDC för varje valuta (holdings × close-pris),
          SUM (summan av alla USDC-värden)

        Sparas till DATA_AREA_ROOT_DIR/visualize/debug.csv.
        """
        if not dfs:
            log.info("Ingen kursdata – debug-CSV skrivs inte")
            return

        # Bygg gemensamt tidsindex
        idx: Optional[pd.DatetimeIndex] = None
        for df in dfs.values():
            dti = pd.DatetimeIndex(df["datetime"])
            idx = dti if idx is None else idx.union(dti)
        if idx is None or len(idx) == 0:
            return
        idx = idx.sort_values()

        # Filtrera till senaste 7 dagarna
        now = pd.Timestamp.now(tz="UTC")
        week_ago = now - pd.Timedelta(days=7)
        idx = idx[idx >= week_ago]
        if len(idx) == 0:
            log.info("Ingen prisdata för senaste veckan – debug-CSV skrivs inte")
            return

        currencies = sorted(dfs.keys())
        positions: Dict[str, pd.Series] = {}
        price_series: Dict[str, pd.Series] = {}

        # Läs portföljsaldo en gång – används för att förankra varje valuta
        _portfolio_balances: Dict[str, float] = {}
        portfolio_file = self.data_root / "portfolio" / "portfolio.json"
        if portfolio_file.exists():
            try:
                with open(portfolio_file, "r", encoding="utf-8") as _pf:
                    _portfolio_data = json.load(_pf)
                for _asset, _info in _portfolio_data.get("balances", {}).items():
                    try:
                        _portfolio_balances[_asset.upper()] = float(_info.get("total", 0))
                    except (ValueError, TypeError):
                        pass
                log.info("Läste portföljsaldon från portfolio.json: %s", list(_portfolio_balances.keys()))
            except Exception as e:
                log.warning("Kunde inte läsa portföljsaldon från portfolio.json: %s", e)

        for currency in currencies:
            df = dfs[currency]
            currency_upper = currency.upper()
            currency_trades = [
                t for t in trades
                if str(t.get("symbol", "")).upper().startswith(currency_upper)
            ]

            current_balance = _portfolio_balances.get(currency_upper, 0.0)

            trade_events: List[tuple] = []
            for t in currency_trades:
                t_ms = t.get("time")
                if not t_ms:
                    continue
                try:
                    qty = float(t.get("qty", 0))
                except (ValueError, TypeError):
                    continue
                if qty <= 0:
                    continue
                delta = qty if t.get("isBuyer", False) else -qty
                trade_events.append((pd.Timestamp(t_ms, unit="ms", tz="UTC"), delta))

            if trade_events:
                pos_s = self._reconstruct_balance_history(
                    current_balance, trade_events, idx
                )
            else:
                pos_s = pd.Series(current_balance, index=idx)

            positions[currency_upper] = pos_s
            price_series[currency_upper] = (
                df.set_index("datetime")["Close"]
                .reindex(idx, method="ffill")
                .fillna(0.0)
            )

        # Beräkna USDC-historik förankrad till aktuellt saldo.
        # Formel: usdc_vid_t = current_balance - sum(flöden efter t)
        #   => sista punkten ≈ current_balance; tidigare punkter rekonstrueras bakåt.
        current_usdc_balance = _portfolio_balances.get("USDC", 0.0)
        usdc_events: List[tuple] = []
        for t in trades:
            symbol = str(t.get("symbol", "")).upper()
            if not symbol.endswith("USDC"):
                continue
            t_ms = t.get("time")
            if not t_ms:
                continue
            try:
                quote_qty = float(t.get("quoteQty", 0))
            except (ValueError, TypeError):
                continue
            if quote_qty <= 0:
                continue
            # Köp krypto → USDC minskar; sälj krypto → USDC ökar
            delta = quote_qty if not t.get("isBuyer", False) else -quote_qty
            usdc_events.append((pd.Timestamp(t_ms, unit="ms", tz="UTC"), delta))

        if usdc_events:
            usdc_pos: pd.Series = self._reconstruct_balance_history(
                current_usdc_balance, usdc_events, idx
            )
        else:
            usdc_pos = pd.Series(current_usdc_balance, index=idx)

        # Bygg DataFrame
        row_data: Dict[str, Any] = {"datetime": idx}
        for c in currencies:
            row_data[c.upper()] = positions[c.upper()].values
        row_data["USDC"] = usdc_pos.values
        for c in currencies:
            c_upper = c.upper()
            row_data[f"{c_upper}USDC"] = (
                positions[c_upper] * price_series[c_upper]
            ).values
        sum_vals = usdc_pos.copy()
        for c in currencies:
            c_upper = c.upper()
            sum_vals = sum_vals + positions[c_upper] * price_series[c_upper]
        row_data["SUM"] = sum_vals.values

        debug_df = pd.DataFrame(row_data)
        self._ensure_dir(self.output_dir)
        debug_file = self.output_dir / "debug.csv"
        try:
            debug_df.to_csv(debug_file, index=False)
            log.info("Debug-CSV sparad: %s (%d rader)", debug_file, len(debug_df))
        except Exception as e:
            log.error("Fel vid sparande av debug-CSV: %s", e)

    def _read_ta_signal(self, currency: str) -> str:
        """
        Läs senaste TA-signal för angiven valuta från backtesting-CSV.

        Returnerar 'KÖP', 'SÄLJ', 'NEUTRAL' eller '–' om ingen data finns.
        Signalen hämtas från samma backtesting-fil som används för
        kurshistorikdiagrammet så att Overview-tabben alltid stämmer
        överens med diagrammets bakgrundsfärg.
        """
        _SIGNAL_MAP = {"BUY": "KÖP", "SELL": "SÄLJ", "HOLD": "NEUTRAL"}
        bt_df = self._read_backtest(currency)
        if bt_df is None or bt_df.empty:
            return "–"
        last_signal = str(bt_df.iloc[-1]["signal"]).strip().upper()
        return _SIGNAL_MAP.get(last_signal, "–")

    def _build_portfolio_performance(
        self,
        trades: List[Dict[str, Any]],
        dfs: Dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """
        Beräkna portföljvärde över tid baserat på faktiska innehav.

        Använder samma bakåtrekonstruktionsalgoritm som _write_debug_csv:
        startar från aktuellt saldo i portfolio.json och ångrar varje affärs
        nettoflöde för att ge historiska saldon.

        Vid varje tidpunkt summeras innehav × aktuellt pris för alla valutor
        plus det rekonstruerade USDC-saldot. Värdet returneras i USDC.

        Args:
            trades: Lista med alla trades (isBuyer, qty, symbol, time)
            dfs: Dict med {valuta: DataFrame med 'datetime' och 'Close'}

        Returns:
            DataFrame med kolumnerna 'datetime' och 'portfolio_value' (USDC)
        """
        if not dfs:
            return pd.DataFrame(columns=["datetime", "portfolio_value"])

        # Bygg ett gemensamt tidsindex av alla kursdatas tidsstämplar
        idx: Optional[pd.DatetimeIndex] = None
        for df in dfs.values():
            dti = pd.DatetimeIndex(df["datetime"])
            idx = dti if idx is None else idx.union(dti)
        if idx is None or len(idx) == 0:
            return pd.DataFrame(columns=["datetime", "portfolio_value"])
        idx = idx.sort_values()

        # Läs portföljsaldo – används för att förankra varje valuta (samma som _write_debug_csv)
        _portfolio_balances: Dict[str, float] = {}
        portfolio_file = self.data_root / "portfolio" / "portfolio.json"
        if portfolio_file.exists():
            try:
                with open(portfolio_file, "r", encoding="utf-8") as _pf:
                    _portfolio_data = json.load(_pf)
                for _asset, _info in _portfolio_data.get("balances", {}).items():
                    try:
                        _portfolio_balances[_asset.upper()] = float(_info.get("total", 0))
                    except (ValueError, TypeError):
                        log.warning(
                            "Ogiltigt saldo för %s i portfolio.json: %s",
                            _asset, _info.get("total"),
                        )
                log.info(
                    "Portföljsaldon lästa för performance-diagram: %s",
                    list(_portfolio_balances.keys()),
                )
            except Exception as e:
                log.warning("Kunde inte läsa portföljsaldon från portfolio.json: %s", e)

        portfolio_value = pd.Series(0.0, index=idx)

        for currency, df in dfs.items():
            currency_upper = currency.upper()
            currency_trades = [
                t for t in trades
                if str(t.get("symbol", "")).upper().startswith(currency_upper)
            ]

            current_balance = _portfolio_balances.get(currency_upper, 0.0)

            trade_events: List[tuple] = []
            for t in currency_trades:
                t_ms = t.get("time")
                if not t_ms:
                    continue
                try:
                    qty = float(t.get("qty", 0))
                except (ValueError, TypeError):
                    continue
                if qty <= 0:
                    continue
                delta = qty if t.get("isBuyer", False) else -qty
                trade_events.append((pd.Timestamp(t_ms, unit="ms", tz="UTC"), delta))

            if trade_events:
                # Bin varje affär till sin timkandle via floor('h') och gå bakåt
                # från current_balance för att rekonstruera historiska saldon.
                pos_series = self._reconstruct_balance_history(
                    current_balance, trade_events, idx
                )
            else:
                pos_series = pd.Series(current_balance, index=idx)

            # Prisserie för denna valuta, forward-filld till gemensamt index
            price_series = (
                df.set_index("datetime")["Close"]
                .reindex(idx, method="ffill")
                .fillna(0.0)
            )

            portfolio_value = portfolio_value + pos_series * price_series

        # Lägg till USDC-saldo (samma bakåtrekonstruktion som _write_debug_csv)
        current_usdc_balance = _portfolio_balances.get("USDC", 0.0)
        usdc_events: List[tuple] = []
        for t in trades:
            symbol = str(t.get("symbol", "")).upper()
            if not symbol.endswith("USDC"):
                continue
            t_ms = t.get("time")
            if not t_ms:
                continue
            try:
                quote_qty = float(t.get("quoteQty", 0))
            except (ValueError, TypeError):
                continue
            if quote_qty <= 0:
                continue
            # Köp krypto → USDC minskar; sälj krypto → USDC ökar
            delta = quote_qty if not t.get("isBuyer", False) else -quote_qty
            usdc_events.append((pd.Timestamp(t_ms, unit="ms", tz="UTC"), delta))

        if usdc_events:
            usdc_pos: pd.Series = self._reconstruct_balance_history(
                current_usdc_balance, usdc_events, idx
            )
        else:
            usdc_pos = pd.Series(current_usdc_balance, index=idx)

        portfolio_value = portfolio_value + usdc_pos

        # Filtrera bort tidpunkter utan innehav
        result = pd.DataFrame(
            {"datetime": idx, "portfolio_value": portfolio_value.values}
        )
        result = result[result["portfolio_value"] > 0].reset_index(drop=True)

        if result.empty:
            log.info("Portföljberäkning: inget positivt innehav hittades")
            return pd.DataFrame(columns=["datetime", "portfolio_value"])

        log.info(
            "Portföljvärde beräknat: %d datapunkter, start=%.2f USDC, slut=%.2f USDC",
            len(result),
            result["portfolio_value"].iloc[0],
            result["portfolio_value"].iloc[-1],
        )
        return result

    def generate_portfolio_chart(
        self,
        trades: List[Dict[str, Any]],
        dfs: Dict[str, pd.DataFrame],
    ) -> Optional[str]:
        """
        Generera HTML-div för portföljvärde-fliken.

        Visar portföljets totala värde i USDC (innehav × pris, summerat för alla valutor)
        över tid. Y-axeln visar faktiskt USDC-värde (ej normaliserat).

        Args:
            trades: Lista med alla trades
            dfs: Dict med {valuta: DataFrame med kurshistorik}

        Returns:
            HTML-sträng (div) vid succé, None om ingen data finns
        """
        perf_df = self._build_portfolio_performance(trades, dfs)
        if perf_df.empty:
            log.warning("Ingen portföljdata – hoppar över portföljdiagram")
            return None

        fig = go.Figure()

        fig.add_trace(
            go.Scatter(
                x=perf_df["datetime"],
                y=perf_df["portfolio_value"],
                name="Portföljvärde",
                line=dict(width=2, color="#89dceb"),
                fill="tozeroy",
                fillcolor="rgba(137, 220, 235, 0.08)",
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>Värde: %{y:,.2f} USDC<extra></extra>",
            )
        )

        fig.update_layout(
            title=dict(
                text="Portföljutveckling – totalt värde i USDC",
                font=dict(size=20),
            ),
            xaxis_title="Datum/tid",
            yaxis_title="Portföljvärde (USDC)",
            template="plotly_dark",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=60, r=20, t=80, b=40),
            height=700,
            xaxis=dict(
                rangeselector=dict(
                    buttons=[
                        dict(count=7, label="Senaste veckan", step="day", stepmode="backward"),
                        dict(count=1, label="Senaste månaden", step="month", stepmode="backward"),
                        dict(step="all", label="Allt"),
                    ],
                    bgcolor="#2a2a3e",
                    activecolor="#4a4a6e",
                    font=dict(color="#cdd6f4"),
                ),
                rangeslider=dict(visible=False),
            ),
        )

        last_date = perf_df["datetime"].max()
        if pd.notna(last_date):
            one_month_ago = last_date - pd.DateOffset(months=1)
            fig.update_xaxes(range=[one_month_ago, last_date])

        log.info("Portföljdiagram byggt")
        return fig.to_html(
            full_html=False,
            include_plotlyjs=False,
            div_id="chart-Performance",
        )

    def generate_summary_html(
        self,
        trades: List[Dict[str, Any]],
        dfs: Dict[str, pd.DataFrame],
    ) -> str:
        """
        Generera HTML-div för sammanfattningsfliken.

        Visar:
        - Tabell med nuvarande innehav, USDC-värde och senaste TA-signal per valuta
        - Tabell med senaste tre trades (datum, valuta, belopp, typ, % förändring vid SÄLJ)

        Args:
            trades: Lista med alla trades
            dfs: Dict med {valuta: DataFrame med kurshistorik}

        Returns:
            HTML-sträng (div)
        """
        # Read portfolio balances
        portfolio_balances: Dict[str, float] = {}
        portfolio_file = self.data_root / "portfolio" / "portfolio.json"
        if portfolio_file.exists():
            try:
                with open(portfolio_file, "r", encoding="utf-8") as pf:
                    portfolio_data = json.load(pf)
                for asset, info in portfolio_data.get("balances", {}).items():
                    try:
                        portfolio_balances[asset.upper()] = float(info.get("total", 0))
                    except (ValueError, TypeError):
                        pass
            except Exception as e:
                log.warning("Kunde inte läsa portföljsaldon för sammanfattning: %s", e)

        # Build holdings table rows
        holdings_rows = []
        for currency in self.cfg.currencies:
            currency_upper = currency.upper()
            holdings = portfolio_balances.get(currency_upper, 0.0)
            # Latest close price from history data
            latest_price = 0.0
            usdc_value = 0.0
            df = dfs.get(currency)
            if df is not None and not df.empty:
                try:
                    latest_price = float(df["Close"].iloc[-1])
                    usdc_value = holdings * latest_price
                except (ValueError, TypeError, IndexError):
                    pass
            signal = self._read_ta_signal(currency)
            holdings_rows.append((currency_upper, holdings, latest_price, usdc_value, signal))

        # Add USDC row
        usdc_holdings = portfolio_balances.get("USDC", 0.0)
        holdings_rows.append(("USDC", usdc_holdings, 1.0, usdc_holdings, "–"))

        # Build latest-10-trades table (deduplicate by symbol+id)
        sorted_trades = sorted(trades, key=lambda t: t.get("time") or 0, reverse=True)
        seen_trade_keys: set = set()
        unique_trades: List[Dict[str, Any]] = []
        for t in sorted_trades:
            tid = t.get("id")
            if tid is not None:
                trade_key = (t.get("symbol"), tid)
                if trade_key in seen_trade_keys:
                    continue
                seen_trade_keys.add(trade_key)
            unique_trades.append(t)
        recent_trades = unique_trades[:10]

        # Identify the index of the most recent BUY in the displayed list
        most_recent_buy_idx = next(
            (i for i, t in enumerate(recent_trades) if t.get("isBuyer", False)),
            None,
        )

        trades_rows = []
        for row_idx, trade in enumerate(recent_trades):
            trade_time_ms = trade.get("time")
            dt_str = "–"
            if trade_time_ms:
                dt = datetime.fromtimestamp(trade_time_ms / 1000, tz=timezone.utc)
                dt_str = dt.strftime("%Y-%m-%d %H:%M")

            symbol = str(trade.get("symbol", "–")).upper()
            # Derive currency name by matching against configured currencies
            currency_name = symbol
            for cur in self.cfg.currencies:
                if symbol.startswith(cur.upper()):
                    currency_name = cur.upper()
                    break

            try:
                amount = float(trade.get("quoteQty", 0))
                amount_str = f"{amount:,.2f} USDC"
            except (ValueError, TypeError):
                amount_str = str(trade.get("quoteQty", "–"))

            try:
                price_val = float(trade.get("price", 0))
                price_str = f"{price_val:,.2f}"
            except (ValueError, TypeError):
                price_str = str(trade.get("price", "–"))

            is_buyer = trade.get("isBuyer", False)
            trade_type = "KÖP" if is_buyer else "SÄLJ"

            pct_change = "–"
            if not is_buyer:
                # SÄLJ: visa % förändring mot föregående köp
                preceding_buys = [
                    t for t in trades
                    if str(t.get("symbol", "")).upper().startswith(currency_name)
                    and t.get("isBuyer", False)
                    and (t.get("time") or 0) < (trade_time_ms or 0)
                ]
                if preceding_buys:
                    preceding_buys.sort(key=lambda t: t.get("time") or 0, reverse=True)
                    last_buy = preceding_buys[0]
                    try:
                        buy_price = float(last_buy.get("price", 0))
                        sell_price = float(trade.get("price", 0))
                        if buy_price > 0:
                            pct = (sell_price - buy_price) / buy_price * 100
                            sign = "+" if pct >= 0 else ""
                            pct_change = f"{sign}{pct:.2f}%"
                    except (ValueError, TypeError):
                        pass
            elif row_idx == most_recent_buy_idx:
                # KÖP: visa % förändring från köpkurs mot senaste kurs –
                # endast om det finns aktivt innehav i portföljen
                cur_holdings = portfolio_balances.get(currency_name, 0.0)
                cur_df = dfs.get(currency_name)
                if cur_holdings > 0 and cur_df is not None and not cur_df.empty:
                    try:
                        latest_price = float(cur_df["Close"].iloc[-1])
                        buy_price = float(trade.get("price", 0))
                        if buy_price > 0:
                            pct = (latest_price - buy_price) / buy_price * 100
                            sign = "+" if pct >= 0 else ""
                            pct_change = f"{sign}{pct:.2f}%"
                    except (ValueError, TypeError, IndexError):
                        pass

            trades_rows.append((dt_str, currency_name, amount_str, price_str, trade_type, pct_change))

        # Build HTML
        def _signal_td(signal: str) -> str:
            css = ""
            if signal == "KÖP":
                css = ' class="vh-sum-buy"'
            elif signal == "SÄLJ":
                css = ' class="vh-sum-sell"'
            return f"<td{css}>{signal}</td>"

        def _pct_td(pct: str) -> str:
            if pct == "–":
                return f"<td>{pct}</td>"
            css = ' class="vh-sum-pos"' if pct.startswith("+") else ' class="vh-sum-neg"'
            return f"<td{css}>{pct}</td>"

        holdings_tbody = ""
        for (cur, holdings, latest_price, usdc_value, signal) in holdings_rows:
            price_col = f"{latest_price:,.2f}" if latest_price else "–"
            holdings_tbody += (
                "<tr>"
                f"<td>{cur}</td>"
                f"<td>{holdings:.6f}</td>"
                f"<td>{price_col}</td>"
                f"<td>{usdc_value:,.2f}</td>"
                f"{_signal_td(signal)}"
                "</tr>\n"
            )

        trades_tbody = ""
        for (dt_str, cur, amount_str, price_str, trade_type, pct_change) in trades_rows:
            type_css = ' class="vh-sum-buy"' if trade_type == "KÖP" else ' class="vh-sum-sell"'
            trades_tbody += (
                "<tr>"
                f"<td>{dt_str}</td>"
                f"<td>{cur}</td>"
                f"<td>{amount_str}</td>"
                f"<td>{price_str}</td>"
                f"<td{type_css}>{trade_type}</td>"
                f"{_pct_td(pct_change)}"
                "</tr>\n"
            )

        if not trades_rows:
            trades_tbody = '<tr><td colspan="6" style="text-align:center;color:#6c7086">Inga trades</td></tr>\n'

        log.info("Overview-fliken byggd")
        return (
            '<div id="chart-Overview" style="padding:20px 32px">\n'
            '<h2 class="vh-sum-h2">Portföljöversikt</h2>\n'
            '<table class="vh-sum-table">\n'
            "<thead><tr>"
            "<th>Valuta</th><th>Innehav</th><th>Senaste kurs</th><th>Värde (USDC)</th><th>Senaste TA-signal</th>"
            "</tr></thead>\n"
            f"<tbody>\n{holdings_tbody}</tbody>\n"
            "</table>\n"
            '<h2 class="vh-sum-h2" style="margin-top:32px">Senaste trades</h2>\n'
            '<table class="vh-sum-table">\n'
            "<thead><tr>"
            "<th>Datum</th><th>Valuta</th><th>Belopp</th><th>Kurs</th><th>Typ</th><th>Förändring</th>"
            "</tr></thead>\n"
            f"<tbody>\n{trades_tbody}</tbody>\n"
            "</table>\n"
            "</div>"
        )

    def generate_chart(self, currency: str, trades: List[Dict[str, Any]]) -> Optional[str]:
        """
        Generera HTML-div för angiven valuta.

        Args:
            currency: Valutasymbol (t.ex. "BTC")
            trades: Lista med alla trades (filtreras internt för currency)

        Returns:
            HTML-sträng (div) vid succé, None vid fel
        """
        df = self._read_history(currency)
        if df is None or df.empty:
            log.warning("Ingen kurshistorik för %s – hoppar över diagram", currency)
            return None

        currency_trades = self._filter_trades_for_currency(trades, currency)
        backtest_df = self._read_backtest(currency)

        # Skapa subplot med candlestick och volym
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            row_heights=[0.75, 0.25],
            vertical_spacing=0.03,
        )

        # Candlestick-diagram
        fig.add_trace(
            go.Candlestick(
                x=df["datetime"],
                open=df["Open"],
                high=df["High"],
                low=df["Low"],
                close=df["Close"],
                name="Kurs",
                increasing_line_color="#4d8a85",
                decreasing_line_color="#c97474",
            ),
            row=1, col=1,
        )

        # Volym-staplar
        fig.add_trace(
            go.Bar(
                x=df["datetime"],
                y=df["Volume"],
                name="Volym",
                marker_color="rgba(100, 149, 237, 0.5)",
                showlegend=True,
            ),
            row=2, col=1,
        )

        # Lägg till köp- och säljmarkeringar om det finns trades
        if currency_trades:
            history_start = df["datetime"].min()
            history_end = df["datetime"].max()

            buy_times, buy_prices, buy_labels = [], [], []
            sell_times, sell_prices, sell_labels = [], [], []

            last_buy_price: Optional[float] = None
            sorted_trades = sorted(
                currency_trades, key=lambda t: t.get("time") or 0
            )
            for trade in sorted_trades:
                trade_time_ms = trade.get("time")
                if not trade_time_ms:
                    continue
                trade_dt = datetime.fromtimestamp(
                    trade_time_ms / 1000, tz=timezone.utc
                )
                # Visa bara trades inom kurshistorikens tidsintervall
                if not (history_start <= trade_dt <= history_end):
                    continue

                try:
                    price = float(trade.get("price", 0))
                except (ValueError, TypeError):
                    continue

                is_buyer = trade.get("isBuyer", False)
                if is_buyer:
                    last_buy_price = price
                    label = self._format_trade_label(trade)
                    buy_times.append(trade_dt)
                    buy_prices.append(price)
                    buy_labels.append(label)
                else:
                    label = self._format_trade_label(trade, buy_price=last_buy_price)
                    sell_times.append(trade_dt)
                    sell_prices.append(price)
                    sell_labels.append(label)

            if buy_times:
                fig.add_trace(
                    go.Scatter(
                        x=buy_times,
                        y=buy_prices,
                        mode="markers",
                        name="Köp",
                        marker=dict(
                            symbol="triangle-up",
                            size=14,
                            color="#00c853",
                            line=dict(color="#ffffff", width=1),
                        ),
                        text=buy_labels,
                        hovertemplate="%{text}<extra></extra>",
                    ),
                    row=1, col=1,
                )

            if sell_times:
                fig.add_trace(
                    go.Scatter(
                        x=sell_times,
                        y=sell_prices,
                        mode="markers",
                        name="Sälj",
                        marker=dict(
                            symbol="triangle-down",
                            size=14,
                            color="#d50000",
                            line=dict(color="#ffffff", width=1),
                        ),
                        text=sell_labels,
                        hovertemplate="%{text}<extra></extra>",
                    ),
                    row=1, col=1,
                )

        # Bakgrundsfärger baserat på backtestsignaler (BUY=grön, SELL=röd)
        if backtest_df is not None and not backtest_df.empty:
            BUY_COLOR = "rgba(0, 80, 30, 0.20)"
            SELL_COLOR = "rgba(80, 0, 0, 0.20)"
            chart_end = df["datetime"].max()
            current_signal: Optional[str] = None
            seg_start = None
            for _, row_bt in backtest_df.iterrows():
                sig = row_bt["signal"]
                dt = row_bt["datetime"]
                if sig != current_signal:
                    if current_signal in ("BUY", "SELL") and seg_start is not None:
                        color = BUY_COLOR if current_signal == "BUY" else SELL_COLOR
                        fig.add_vrect(
                            x0=seg_start, x1=dt,
                            fillcolor=color, layer="below", line_width=0,
                            row="all", col=1,
                        )
                    current_signal = sig
                    seg_start = dt
            # Avsluta sista segmentet
            if current_signal in ("BUY", "SELL") and seg_start is not None:
                seg_end = min(backtest_df["datetime"].max(), chart_end)
                fig.add_vrect(
                    x0=seg_start, x1=seg_end,
                    fillcolor=(BUY_COLOR if current_signal == "BUY" else SELL_COLOR),
                    layer="below", line_width=0,
                    row="all", col=1,
                )

        fig.update_layout(
            title=dict(
                text=f"{currency}/USDT – Kurshistorik med köp och sälj",
                font=dict(size=20),
            ),
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=60, r=20, t=80, b=40),
            height=700,
        )
        fig.update_yaxes(title_text="Pris (USDT)", row=1, col=1)
        fig.update_yaxes(title_text="Volym", row=2, col=1)
        fig.update_xaxes(title_text="Datum/tid", row=2, col=1)
        fig.update_xaxes(
            rangeselector=dict(
                buttons=[
                    dict(count=7, label="Senaste veckan", step="day", stepmode="backward"),
                    dict(count=1, label="Senaste månaden", step="month", stepmode="backward"),
                    dict(step="all", label="Allt"),
                ],
                bgcolor="#2a2a3e",
                activecolor="#4a4a6e",
                font=dict(color="#cdd6f4"),
            ),
            row=1, col=1,
        )

        last_date = df["datetime"].max()
        if pd.notna(last_date):
            one_month_ago = last_date - pd.DateOffset(months=1)
            fig.update_xaxes(range=[one_month_ago, last_date], row=1, col=1)

        log.info("Diagram byggt för %s", currency)
        return fig.to_html(
            full_html=False,
            include_plotlyjs=False,
            div_id=f"chart-{currency}",
        )

    def _build_combined_html(self, charts: Dict[str, str]) -> str:
        """Bygg kombinerat HTML-dokument med flikar för valutaval."""
        created_at = datetime.now(tz=ZoneInfo("Europe/Stockholm")).strftime("%Y-%m-%d %H:%M")

        # Separera valutaflikar från specialflikarna
        _special = {"Performance", "Overview"}
        currency_keys = [c for c in charts if c not in _special]
        has_portfolio = "Performance" in charts
        has_summary = "Overview" in charts
        all_keys = (
            currency_keys
            + (["Performance"] if has_portfolio else [])
            + (["Overview"] if has_summary else [])
        )

        def _tab_button(c: str, active: bool) -> str:
            if c == "Performance":
                extra_class = " vh-tab-portfolio"
            elif c == "Overview":
                extra_class = " vh-tab-summary"
            else:
                extra_class = ""
            active_class = " vh-tab-active" if active else ""
            return (
                '<button class="vh-tab{extra}{active}" id="tab-{c}" '
                'onclick="showChart(\'{c}\')">{c}</button>'.format(
                    c=c, extra=extra_class, active=active_class
                )
            )

        tab_parts = [_tab_button(c, i == 0) for i, c in enumerate(all_keys)]
        # Lägg in en separator före specialflikarna om det finns valutaflikar
        if (has_portfolio or has_summary) and currency_keys:
            tab_parts.insert(len(currency_keys), '<span class="vh-tab-sep"></span>')
        tabs_html = "\n".join(tab_parts)

        chart_sections = "\n".join(
            '<div id="wrapper-{c}" style="display:{d}">{html}</div>'.format(
                c=c,
                d="" if i == 0 else "none",
                html=charts[c],
            )
            for i, c in enumerate(all_keys)
        )

        key_json = ", ".join(f'"{c}"' for c in all_keys)

        combined_js = (
            "var _currencies = [" + key_json + "];\n"
            "function _tabClass(x, active) {\n"
            "  var cls = 'vh-tab';\n"
            "  if (x === 'Performance') cls += ' vh-tab-portfolio';\n"
            "  if (x === 'Overview') cls += ' vh-tab-summary';\n"
            "  if (active) cls += ' vh-tab-active';\n"
            "  return cls;\n"
            "}\n"
            "function applyLastMonth(chartId) {\n"
            "  var el = document.getElementById(chartId);\n"
            "  if (!el || !el.data || !el.data[0]) return;\n"
            "  var xs = el.data[0].x;\n"
            "  if (!xs || !xs.length) return;\n"
            "  var lastDate = new Date(xs[xs.length - 1]);\n"
            "  var startDate = new Date(lastDate);\n"
            "  startDate.setMonth(startDate.getMonth() - 1);\n"
            "  Plotly.relayout(el, {\n"
            "    'xaxis.range[0]': startDate.toISOString(),\n"
            "    'xaxis.range[1]': lastDate.toISOString(),\n"
            "    'xaxis.rangeselector.active': 1\n"
            "  });\n"
            "}\n"
            "function showChart(c) {\n"
            "  _currencies.forEach(function(x) {\n"
            "    var w = document.getElementById('wrapper-' + x);\n"
            "    if (w) w.style.display = x === c ? '' : 'none';\n"
            "    var t = document.getElementById('tab-' + x);\n"
            "    if (t) t.className = _tabClass(x, x === c);\n"
            "  });\n"
            "  var el = document.getElementById('chart-' + c);\n"
            "  if (el) {\n"
            "    Plotly.Plots.resize(el);\n"
            "    applyLastMonth('chart-' + c);\n"
            "  }\n"
            "}\n"
            "window.addEventListener('load', function() {\n"
            "  if (_currencies.length > 0) applyLastMonth('chart-' + _currencies[0]);\n"
            "});\n"
        )

        return (
            "<!DOCTYPE html>\n"
            '<html lang="sv">\n'
            "<head>\n"
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            "<title>Kurshistorik</title>\n"
            f"<script>{get_plotlyjs()}</script>\n"
            "<style>\n"
            "body{background:#1a1a2e;color:#cdd6f4;font-family:sans-serif;margin:0;padding:0}\n"
            ".vh-tabs{padding:0 20px;background:#16213e;border-bottom:1px solid #45475a;"
            "display:flex;align-items:flex-end;gap:4px;overflow-x:auto;flex-wrap:nowrap;"
            "-webkit-overflow-scrolling:touch}\n"
            ".vh-tab{background:#2a2a3e;color:#cdd6f4;border:1px solid #45475a;"
            "border-bottom:none;border-radius:6px 6px 0 0;padding:10px 20px;"
            "font-size:15px;cursor:pointer;margin-bottom:-1px;transition:background 0.15s;"
            "flex-shrink:0}\n"
            ".vh-tab:hover{background:#3a3a5e}\n"
            ".vh-tab-active{background:#1a1a2e;color:#89dceb;border-bottom:1px solid #1a1a2e}\n"
            ".vh-tab-portfolio{color:#a6e3a1;border-color:#a6e3a1}\n"
            ".vh-tab-portfolio.vh-tab-active{color:#a6e3a1}\n"
            ".vh-tab-summary{color:#cba6f7;border-color:#cba6f7}\n"
            ".vh-tab-summary.vh-tab-active{color:#cba6f7}\n"
            ".vh-tab-sep{width:1px;background:#45475a;margin:6px 4px;align-self:stretch}\n"
            ".vh-created-at{margin-left:auto;color:#4a5a80;font-size:11px;padding-bottom:10px;align-self:flex-end;white-space:nowrap}\n"
            ".vh-sum-h2{color:#cdd6f4;margin-top:16px;font-size:18px}\n"
            ".vh-sum-table{border-collapse:collapse;min-width:480px;font-size:14px}\n"
            ".vh-sum-table th{background:#16213e;color:#89b4fa;padding:8px 16px;"
            "text-align:left;border-bottom:2px solid #45475a;white-space:nowrap}\n"
            ".vh-sum-table td{padding:7px 16px;border-bottom:1px solid #313244;color:#cdd6f4}\n"
            ".vh-sum-table tr:hover td{background:#1e1e2e}\n"
            ".vh-sum-buy{color:#a6e3a1;font-weight:bold}\n"
            ".vh-sum-sell{color:#f38ba8;font-weight:bold}\n"
            ".vh-sum-pos{color:#a6e3a1}\n"
            ".vh-sum-neg{color:#f38ba8}\n"
            "</style>\n"
            "</head>\n"
            "<body>\n"
            '<div class="vh-tabs">\n'
            f"{tabs_html}\n"
            f'<span class="vh-created-at">{created_at}</span>\n'
            "</div>\n"
            f"{chart_sections}\n"
            f"<script>{combined_js}</script>\n"
            "</body>\n"
            "</html>"
        )

    def run(self) -> bool:
        """
        Generera ett kombinerat diagram för alla konfigurerade valutor
        samt en separat portföljperformance-flik.

        Returns:
            True om minst ett diagram genererades framgångsrikt
        """
        log.info("=== Startar VisualizeHistory ===")
        trades = self._read_trades()
        charts: Dict[str, str] = {}
        dfs: Dict[str, pd.DataFrame] = {}

        for currency in self.cfg.currencies:
            try:
                df = self._read_history(currency)
                if df is not None and not df.empty:
                    dfs[currency] = df
                div = self.generate_chart(currency, trades)
                if div is not None:
                    charts[currency] = div
                    log.info("Diagram genererat för %s", currency)
                else:
                    log.warning("Kunde inte generera diagram för %s", currency)
            except Exception as e:
                log.error("Oväntat fel vid generering av diagram för %s: %s", currency, e)

        # Skriv debug-CSV oavsett om diagram genererats
        try:
            self._write_debug_csv(trades, dfs)
        except Exception as e:
            log.error("Fel vid skrivning av debug-CSV: %s", e)

        if not charts:
            log.info(
                "VisualizeHistory klar: 0/%d diagram genererade",
                len(self.cfg.currencies),
            )
            return False

        # Generera portföljperformance-flik
        try:
            portfolio_div = self.generate_portfolio_chart(trades, dfs)
            if portfolio_div is not None:
                charts["Performance"] = portfolio_div
                log.info("Portföljdiagram genererat")
            else:
                log.info("Inget portföljdiagram genererat (inga trades med innehav)")
        except Exception as e:
            log.error("Oväntat fel vid generering av portföljdiagram: %s", e)

        # Generera overview-flik
        try:
            charts["Overview"] = self.generate_summary_html(trades, dfs)
        except Exception as e:
            log.error("Oväntat fel vid generering av overview: %s", e)

        self._ensure_dir(self.output_dir)
        html_file = self.output_dir / "history_chart.html"
        html_content = self._build_combined_html(charts)

        try:
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(html_content)
            log.info("Kombinerat diagram sparat: %s", html_file)
        except Exception as e:
            log.error("Fel vid sparande av kombinerat diagram: %s", e)
            return False

        _special = {"Performance", "Overview"}
        log.info(
            "VisualizeHistory klar: %d/%d valutadiagram genererade",
            len([c for c in charts if c not in _special]),
            len(self.cfg.currencies),
        )
        return True


def visualize_history_main(cfg: Config) -> None:
    """Entrypoint för att köra visualisering från main.py."""
    viz = VisualizeHistory(cfg)
    success = viz.run()
    if not success:
        log.error("VisualizeHistory misslyckades – inga diagram genererades")
        raise SystemExit(1)

#!/usr/bin/env python3
"""
VisualizeHistory - Generera interaktivt kurshistorikdiagram med köp/säljmarkeringar.

Läser kurshistorik från DATA_AREA_ROOT_DIR/history/<currency>/<currency>_history.csv
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

    def _read_history(self, currency: str) -> Optional[pd.DataFrame]:
        """Läs kurshistorik för angiven valuta."""
        csv_file = self.history_root / currency / f"{currency}_history.csv"
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

        log.info("Portföljdiagram byggt")
        return fig.to_html(
            full_html=False,
            include_plotlyjs=False,
            div_id="chart-Performance",
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
                        customdata=buy_labels,
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
                        customdata=sell_labels,
                    ),
                    row=1, col=1,
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

        log.info("Diagram byggt för %s", currency)
        return fig.to_html(
            full_html=False,
            include_plotlyjs=False,
            div_id=f"chart-{currency}",
        )

    def _build_combined_html(self, charts: Dict[str, str]) -> str:
        """Bygg kombinerat HTML-dokument med flikar för valutaval."""
        created_at = datetime.now(tz=ZoneInfo("Europe/Stockholm")).strftime("%Y-%m-%d %H:%M")

        # Separera valutaflikar från portföljfliken
        currency_keys = [c for c in charts if c != "Performance"]
        has_portfolio = "Performance" in charts
        all_keys = currency_keys + (["Performance"] if has_portfolio else [])

        def _tab_button(c: str, active: bool) -> str:
            extra_class = " vh-tab-portfolio" if c == "Performance" else ""
            active_class = " vh-tab-active" if active else ""
            return (
                '<button class="vh-tab{extra}{active}" id="tab-{c}" '
                'onclick="showChart(\'{c}\')">{c}</button>'.format(
                    c=c, extra=extra_class, active=active_class
                )
            )

        tab_parts = [_tab_button(c, i == 0) for i, c in enumerate(all_keys)]
        # Lägg in en separator före portföljfliken om det finns valutaflikar
        if has_portfolio and currency_keys:
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

        info_box_html = (
            '<div id="trade-info" style="'
            "display:none; position:fixed; top:80px; right:20px; "
            "background:#1e1e2e; color:#cdd6f4; border:1px solid #45475a; "
            "border-radius:8px; padding:16px; max-width:320px; "
            "font-family:monospace; font-size:13px; z-index:9999; "
            'box-shadow:0 4px 16px rgba(0,0,0,0.5);">'
            '<button onclick="this.parentElement.style.display=\'none\'" '
            'style="float:right;background:none;border:none;color:#cdd6f4;'
            'font-size:16px;cursor:pointer;">✕</button>'
            "<b>Handelsinformation</b><br><br>"
            "</div>"
        )

        key_json = ", ".join(f'"{c}"' for c in all_keys)

        combined_js = (
            "var _currencies = [" + key_json + "];\n"
            "function _tabClass(x, active) {\n"
            "  var cls = 'vh-tab';\n"
            "  if (x === 'Performance') cls += ' vh-tab-portfolio';\n"
            "  if (active) cls += ' vh-tab-active';\n"
            "  return cls;\n"
            "}\n"
            "function showChart(c) {\n"
            "  _currencies.forEach(function(x) {\n"
            "    var w = document.getElementById('wrapper-' + x);\n"
            "    if (w) w.style.display = x === c ? '' : 'none';\n"
            "    var t = document.getElementById('tab-' + x);\n"
            "    if (t) t.className = _tabClass(x, x === c);\n"
            "  });\n"
            "  var el = document.getElementById('chart-' + c);\n"
            "  if (el) Plotly.Plots.resize(el);\n"
            "}\n"
            "window.addEventListener('load', function() {\n"
            "  _currencies.forEach(function(c) {\n"
            "    var el = document.getElementById('chart-' + c);\n"
            "    if (el) el.on('plotly_click', function(data) {\n"
            "      var pt = data.points[0];\n"
            "      var box = document.getElementById('trade-info');\n"
            "      if (pt && pt.customdata) {\n"
            "        box.innerHTML = pt.customdata.replace(/<br>/g, '<br>');\n"
            "        box.style.display = 'block';\n"
            "      } else {\n"
            "        box.style.display = 'none';\n"
            "      }\n"
            "    });\n"
            "  });\n"
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
            "display:flex;align-items:flex-end;gap:4px}\n"
            ".vh-tab{background:#2a2a3e;color:#cdd6f4;border:1px solid #45475a;"
            "border-bottom:none;border-radius:6px 6px 0 0;padding:10px 20px;"
            "font-size:15px;cursor:pointer;margin-bottom:-1px;transition:background 0.15s}\n"
            ".vh-tab:hover{background:#3a3a5e}\n"
            ".vh-tab-active{background:#1a1a2e;color:#89dceb;border-bottom:1px solid #1a1a2e}\n"
            ".vh-tab-portfolio{color:#a6e3a1;border-color:#a6e3a1}\n"
            ".vh-tab-portfolio.vh-tab-active{color:#a6e3a1}\n"
            ".vh-tab-sep{width:1px;background:#45475a;margin:6px 4px;align-self:stretch}\n"
            ".vh-created-at{margin-left:auto;color:#4a5a80;font-size:11px;padding-bottom:10px;align-self:flex-end;white-space:nowrap}\n"
            "</style>\n"
            "</head>\n"
            "<body>\n"
            '<div class="vh-tabs">\n'
            f"{tabs_html}\n"
            f'<span class="vh-created-at">{created_at}</span>\n'
            "</div>\n"
            f"{chart_sections}\n"
            f"{info_box_html}\n"
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

        log.info(
            "VisualizeHistory klar: %d/%d valutadiagram genererade",
            len([c for c in charts if c != "Performance"]),
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

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

    def _format_trade_label(self, trade: Dict[str, Any]) -> str:
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

        return (
            f"<b>{action}</b><br>"
            f"Symbol: {symbol}<br>"
            f"Pris: {price}<br>"
            f"Mängd: {qty}<br>"
            f"Totalt (quote): {quote_qty}<br>"
            f"Avgift: {commission} {commission_asset}<br>"
            f"Tid: {time_str}"
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
                increasing_line_color="#26a69a",
                decreasing_line_color="#ef5350",
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

            for trade in currency_trades:
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

                label = self._format_trade_label(trade)
                is_buyer = trade.get("isBuyer", False)
                if is_buyer:
                    buy_times.append(trade_dt)
                    buy_prices.append(price)
                    buy_labels.append(label)
                else:
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
        currencies = list(charts.keys())

        tabs_html = "\n".join(
            '<button class="vh-tab{active}" id="tab-{c}" onclick="showChart(\'{c}\')">{c}</button>'.format(
                c=c,
                active=" vh-tab-active" if i == 0 else "",
            )
            for i, c in enumerate(currencies)
        )

        chart_sections = "\n".join(
            '<div id="wrapper-{c}" style="display:{d}">{html}</div>'.format(
                c=c,
                d="" if i == 0 else "none",
                html=charts[c],
            )
            for i, c in enumerate(currencies)
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

        currency_json = ", ".join(f'"{c}"' for c in currencies)

        combined_js = (
            "var _currencies = [" + currency_json + "];\n"
            "function showChart(c) {\n"
            "  _currencies.forEach(function(x) {\n"
            "    var w = document.getElementById('wrapper-' + x);\n"
            "    if (w) w.style.display = x === c ? '' : 'none';\n"
            "    var t = document.getElementById('tab-' + x);\n"
            "    if (t) t.className = x === c ? 'vh-tab vh-tab-active' : 'vh-tab';\n"
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
            "</style>\n"
            "</head>\n"
            "<body>\n"
            '<div class="vh-tabs">\n'
            f"{tabs_html}\n"
            "</div>\n"
            f"{chart_sections}\n"
            f"{info_box_html}\n"
            f"<script>{combined_js}</script>\n"
            "</body>\n"
            "</html>"
        )

    def run(self) -> bool:
        """
        Generera ett kombinerat diagram för alla konfigurerade valutor.

        Returns:
            True om minst ett diagram genererades framgångsrikt
        """
        log.info("=== Startar VisualizeHistory ===")
        trades = self._read_trades()
        charts: Dict[str, str] = {}

        for currency in self.cfg.currencies:
            try:
                div = self.generate_chart(currency, trades)
                if div is not None:
                    charts[currency] = div
                    log.info("Diagram genererat för %s", currency)
                else:
                    log.warning("Kunde inte generera diagram för %s", currency)
            except Exception as e:
                log.error("Oväntat fel vid generering av diagram för %s: %s", currency, e)

        if not charts:
            log.info(
                "VisualizeHistory klar: 0/%d diagram genererade",
                len(self.cfg.currencies),
            )
            return False

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
            "VisualizeHistory klar: %d/%d diagram genererade",
            len(charts),
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

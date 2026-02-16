#!/usr/bin/env python3
"""
ValidateCollectedData

Validerar att insamlad data finns på väntade platser och i förväntat antal:
- För varje valuta i Config.currencies ska det finnas exakt 1 fil i:
  DATA_AREA_ROOT_DIR/history/<CURRENCY>/
- Precis 1 fil i DATA_AREA_ROOT_DIR/portfolio/
- Precis 1 fil i DATA_AREA_ROOT_DIR/trades/

Skriptet loggar felaktigheter och avslutar med 0 vid succé eller 1 vid fel.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Dict

from .config import Config
from .assert_env import assert_env_and_report

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class ValidateCollectedData:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.data_root = Path(cfg.data_area_root_dir)

    @staticmethod
    def _list_regular_files(p: Path) -> List[Path]:
        """Returnera lista med vanliga filer (ingen katalog) i given katalog. Ignorera dolda filer som börjar med '.'."""
        if not p.exists() or not p.is_dir():
            return []
        return [f for f in sorted(p.iterdir()) if f.is_file() and not f.name.startswith(".")]

    def _check_history(self) -> Dict[str, List[str]]:
        """
        Kontrollera history/<currency>/ för varje currency i cfg.currencies.
        Returnerar dict med nycklar 'ok' (list of currencies ok) och 'errors' (list of felmeddelanden).
        """
        res_ok: List[str] = []
        res_err: List[str] = []

        history_root = self.data_root / "history"
        for cur in self.cfg.currencies:
            cur_dir = history_root / cur
            files = self._list_regular_files(cur_dir)
            if not cur_dir.exists():
                res_err.append(f"History-mappen saknas för valuta '{cur}': {cur_dir}")
            elif len(files) == 0:
                res_err.append(f"Ingen fil hittades i {cur_dir} för valuta '{cur}'")
            elif len(files) > 1:
                names = ", ".join([f.name for f in files])
                res_err.append(f"Flera filer hittades i {cur_dir} för valuta '{cur}': {names}")
            else:
                res_ok.append(f"{cur} -> {files[0].name}")
        return {"ok": res_ok, "errors": res_err}

    def _check_portfolio(self) -> Dict[str, List[str]]:
        """
        Kontrollera att portfolio-mappen innehåller exakt 1 fil.
        """
        res_ok: List[str] = []
        res_err: List[str] = []

        portfolio_dir = self.data_root / "portfolio"
        files = self._list_regular_files(portfolio_dir)
        if not portfolio_dir.exists():
            res_err.append(f"Portfolio-mappen saknas: {portfolio_dir}")
        elif len(files) == 0:
            res_err.append(f"Ingen fil hittades i portfolio-mappen: {portfolio_dir}")
        elif len(files) > 1:
            names = ", ".join([f.name for f in files])
            res_err.append(f"Flera filer hittades i portfolio-mappen: {names}")
        else:
            res_ok.append(files[0].name)
        return {"ok": res_ok, "errors": res_err}

    def _check_trades(self) -> Dict[str, List[str]]:
        """
        Kontrollera att trades-mappen innehåller exakt 1 fil.
        """
        res_ok: List[str] = []
        res_err: List[str] = []

        trades_dir = self.data_root / "trades"
        files = self._list_regular_files(trades_dir)
        if not trades_dir.exists():
            res_err.append(f"Trades-mappen saknas: {trades_dir}")
        elif len(files) == 0:
            res_err.append(f"Ingen fil hittades i trades-mappen: {trades_dir}")
        elif len(files) > 1:
            names = ", ".join([f.name for f in files])
            res_err.append(f"Flera filer hittades i trades-mappen: {names}")
        else:
            res_ok.append(files[0].name)
        return {"ok": res_ok, "errors": res_err}

    def run(self) -> bool:
        """
        Kör alla valideringar. Loggar resultat och returnerar True om allt är OK, annars False.
        """
        log.info("Startar validering av insamlad data under: %s", self.data_root)

        problems: List[str] = []
        ok_messages: List[str] = []

        hist = self._check_history()
        ok_messages.extend([f"HISTORY: {m}" for m in hist["ok"]])
        problems.extend([f"HISTORY: {e}" for e in hist["errors"]])

        port = self._check_portfolio()
        ok_messages.extend([f"PORTFOLIO: {m}" for m in port["ok"]])
        problems.extend([f"PORTFOLIO: {e}" for e in port["errors"]])

        trades = self._check_trades()
        ok_messages.extend([f"TRADES: {m}" for m in trades["ok"]])
        problems.extend([f"TRADES: {e}" for e in trades["errors"]])

        if ok_messages:
            for m in ok_messages:
                log.info(m)

        if problems:
            log.error("Validering misslyckades med följande problem (%d):", len(problems))
            for p in problems:
                log.error(" - %s", p)
            return False

        log.info("Validering lyckades: korrekt antal filer för history/portfolio/trades.")
        return True


# Module-level convenience function ------------------------------------------------------

def validate_collected_data(cfg: Config) -> None:
    """
    Backwards/extern-vis entrypoint. Kastar SystemExit(1) om valideringen misslyckas.
    """
    log.info("=== Startar CollectedDataValidation ===")
    validator = ValidateCollectedData(cfg)
    ok = validator.run()
    if not ok:
        raise SystemExit(1)


# CLI-stöd: körs direkt ---------------------------------------------------------------

if __name__ == "__main__":
    """
    Kör från kommandoraden. Hämtar env via assert_env_and_report() för att få Config.
    Ex:
      python3 src/validate_collected_data.py
    """
    try:
        cfg = assert_env_and_report()
    except Exception as e:
        log.error("Konfig kunde inte laddas: %s", e)
        raise SystemExit(2)

    success = ValidateCollectedData(cfg).run()
    raise SystemExit(0 if success else 1)
# CryptoHunk2.0 (start)

Detta är en basstruktur för CryptoHunk2.0. Källkod ligger i `cryptohunk2/`.

Syfte i denna initiala commit:
- Implementerat steg 1: AssertEnv — validerar nödvändiga miljövariabler och bygger en Config.
- Tillhandahåller `cryptohunk2/main.py` som orchestrator/entrypoint.
- En `run.sh` för att köra programmet från shell.

Hur man kör:
1. Sätt miljövariablerna (exempel):
   - CURRENCIES="BNB,ETH,SOL"
   - BINANCE_KEY, BINANCE_SECRET
   - BINANCE_TRADING_URL (URL som används för trade-anrop)
   - DATA_AREA_ROOT_DIR
   - CURRENCY_HISTORY_PERIOD
   - CURRENCY_HISTORY_NOF_ELEMENTS (heltal)
   - TRADE_THRESHOLD (float)
   - DRY_RUN (true/false, valfritt)

2. Prepare Python:
   - pyenv install $(cat .python-version)  # optional
   - python -m venv .venv
   - source .venv/bin/activate
   - pip install -r requirements.txt

3. Install and configure `run.sh`:
   - cp run.sh.template run.sh
   - Edit `run.sh` to add environment variables (do not commit)
   - chmod +x run.sh
   - ./run.sh

Eller direkt:
   python3 -m cryptohunk2.main --dump-config

Nästa steg att implementera:
- Hämta historisk prisdata (steg: fetch_history.py)
- Häm
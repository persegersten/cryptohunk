```markdown
Detta är en basstruktur för CryptoHunk2.0 (hunk2). Källkod ligger i `hunk2/src/`.

Ny miljövariabel:
- QUOTE_ASSETS — kommaseparerad lista med vilka quote-valutor som ska användas när trades hämtas (default: "USDT,USDC")

Exempel (bash):
export CURRENCIES="BNB,ETH,SOL"
export QUOTE_ASSETS="USDT,USDC"   # Lägg till BUSD eller andra quotes vid behov
export BINANCE_KEY="din_key"
export BINANCE_SECRET="din_secret"
export BINANCE_TRADING_URL="https://www.binance.com/api/v3/order"
export DATA_AREA_ROOT_DIR="/home/perseg/dev/cryptotrader/tmp/cryptohunk_data"
export CURRENCY_HISTORY_PERIOD="1h"
export CURRENCY_HISTORY_NOF_ELEMENTS="100"
export TRADE_THRESHOLD="0.02"
export DRY_RUN="true"

Kör:
chmod +x run.sh
./run.sh
```
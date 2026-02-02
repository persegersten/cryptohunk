```markdown
Detta är en basstruktur för CryptoHunk2.0 (hunk2). Källkod ligger i `hunk2/src/`.

## Moduler

1. **assert_env** - Validerar miljövariabler och skapar Config-objekt
2. **clean_data** - Rensar data-området
3. **collect_data** - Hämtar data från Binance (historik, portfolio, trades)
4. **validate_collected_data** - Validerar att insamlad data finns
5. **summarize_portfolio** - Skapar sammanställning av portfolio med värden och förändringar

## Ny funktionalitet: Portfolio Summarization

Modulen `summarize_portfolio` skapar en CSV-sammanställning som innehåller:
- Aktuellt värde för varje valuta i USDC
- Föregående köpvärde från tradehistorik
- Procentuell förändring sedan senaste köp
- Absolut värdeförändring i USDC sedan senaste köp
- Hanterar valutor som saknas i portfolio (markeras som 0)

Output sparas i: `DATA_AREA_ROOT_DIR/summarised/portfolio.csv`

CSV-format:
- currency: Valutasymbol (t.ex. BNB, ETH, SOL)
- balance: Totalt saldo i portfolio (0 om saknas)
- current_rate_usdc: Aktuell kurs i USDC
- current_value_usdc: Totalt värde (balance * current_rate, 0 om balance saknas)
- value_change_usdc: Absolut värdeförändring i USDC (current_value - (previous_rate * balance), 0 om ej beräkningsbar)
- previous_rate_usdc: Senaste köpkurs från trades (0 om ingen trade finns)
- percentage_change: Procentuell förändring sedan köp (0 om ej beräkningsbar)

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

För att samla data och skapa sammanställning:
python3 -m hunk2.src.main --collect-data
```
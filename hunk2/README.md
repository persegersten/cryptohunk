Detta är en basstruktur för CryptoHunk2.0 (hunk2). Källkod ligger i `hunk2/src/`.

## Moduler

1. **assert_env** - Validerar miljövariabler och skapar Config-objekt
2. **clean_data** - Rensar data-området
3. **collect_data** - Hämtar data från Binance (historik, portfolio, trades)
4. **validate_collected_data** - Validerar att insamlad data finns
5. **summarize_portfolio** - Skapar sammanställning av portfolio med värden och förändringar
6. **technical_analysis** - Beräknar tekniska indikatorer (RSI, EMA, MACD) på kurshistorik

## Ny funktionalitet: Technical Analysis

Modulen `technical_analysis` beräknar tekniska indikatorer på historisk kursdata:

**Indikatorer som beräknas:**
- RSI (Relative Strength Index, 14 perioder)
- EMA (Exponential Moving Average, 12 perioder)
- EMA (26 perioder)
- EMA (200 perioder)
- MACD (Moving Average Convergence Divergence)
- MACD Signal Line
- MACD Histogram

**Input:** `DATA_AREA_ROOT_DIR/history/<currency>/<currency>_history.csv`

**Output:** `DATA_AREA_ROOT_DIR/ta/<currency>/<currency>_ta.csv`

CSV-format (output):
- Open_Time_ms: Öppningstid i millisekunder
- Close_Time_ms: Stängningstid i millisekunder
- Close: Stängningspris
- RSI_14: RSI med 14 perioders lookback
- EMA_12: Exponentiellt glidande medelvärde (12 perioder)
- EMA_26: Exponentiellt glidande medelvärde (26 perioder)
- EMA_200: Exponentiellt glidande medelvärde (200 perioder)
- MACD: MACD-linje (EMA_12 - EMA_26)
- MACD_Signal: Signal-linje (9-periods EMA av MACD)
- MACD_Histogram: MACD histogram (MACD - MACD_Signal)

**Körning:**
```bash
# Kör teknisk analys på befintlig historik
python3 -m hunk2.src.main --run-ta
```

## Funktionalitet: Portfolio Summarization

Modulen `summarize_portfolio` skapar en CSV-sammanställning som innehåller:
- Aktuellt värde för varje valuta i USDC
- Föregående köpvärde från tradehistorik
- Procentuell förändring sedan senaste köp
- Hanterar valutor som saknas i portfolio (markeras som 0)

Output sparas i: `DATA_AREA_ROOT_DIR/summarised/portfolio.csv`

CSV-format:
- currency: Valutasymbol (t.ex. BNB, ETH, SOL)
- balance: Totalt saldo i portfolio (0 om saknas)
- current_rate_usdc: Aktuell kurs i USDC
- current_value_usdc: Totalt värde (balance * current_rate, 0 om balance saknas)
- previous_rate_usdc: Senaste köpkurs från trades (0 om ingen trade finns)
- percentage_change: Procentuell förändring sedan köp (0 om ej beräkningsbar)

Ny miljövariabel:
- QUOTE_ASSETS — kommaseparerad lista med vilka quote-valutor som ska användas när trades hämtas (default: "USDT,USDC")

## Exempel (bash)

```bash
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

# Kör data collection
python3 -m hunk2.src.main --collect-data

# Kör teknisk analys
python3 -m hunk2.src.main --run-ta
```

## Tester

Tester för modulerna finns i `hunk2/tests/`. Kör tester med:

```bash
python3 -m unittest discover hunk2/tests
```
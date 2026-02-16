Detta är en basstruktur för CryptoHunk2.0 (hunk2). Källkod ligger i `hunk2/src/`.

## Miljövariabler

Systemet konfigureras via miljövariabler. Se `hunk2/src/assert_env.py` för fullständig lista.

**Obligatoriska:**
- `CURRENCIES` - Kommaseparerad lista av valutor (ex: "BTC,ETH,SOL")
- `BINANCE_KEY` - Binance API-nyckel
- `BINANCE_SECRET` - Binance API-hemlighet
- `BINANCE_TRADING_URL` - Binance trading URL
- `DATA_AREA_ROOT_DIR` - Sökväg till dataområde
- `CURRENCY_HISTORY_PERIOD` - Historikperiod (ex: "1h")
- `CURRENCY_HISTORY_NOF_ELEMENTS` - Antal historiska datapunkter
- `TRADE_THRESHOLD` - Minsta värde för handel (i USDC)

**Valfria (med standardvärden):**
- `TAKE_PROFIT_PERCENTAGE` - Vinst-gräns för automatisk försäljning (standard: 10.0%)
- `STOP_LOSS_PERCENTAGE` - Förlust-gräns för automatisk försäljning (standard: 6.0%)
- `QUOTE_ASSETS` - Quote-valutor för trades (standard: "USDT,USDC")
- `DRY_RUN` - Testläge utan riktiga affärer (standard: false)

## Moduler

1. **assert_env** - Validerar miljövariabler och skapar Config-objekt
2. **clean_data** - Rensar data-området
3. **collect_data** - Hämtar data från Binance (historik, portfolio, trades)
4. **validate_collected_data** - Validerar att insamlad data finns
5. **summarize_portfolio** - Skapar sammanställning av portfolio med värden och förändringar
6. **technical_analysis** - Beräknar tekniska indikatorer (RSI, EMA, MACD) på kurshistorik
7. **rebalance_portfolio** - Genererar köp/säljrekommendationer baserat på TA-signaler och innehav
8. **create_trade_plan** - Skapar handelsplan baserat på portfölj och rekommendationer
9. **execute_trade_plan** - Utför handel mot Binance enligt handelsplan

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
- Absolut värdeförändring i USDC sedan senaste köp
- Hanterar valutor som saknas i portfolio (markeras som 0)

Output sparas i: `DATA_AREA_ROOT_DIR/summarised/portfolio.csv`

CSV-format:
- currency: Valutasymbol (t.ex. BNB, ETH, SOL)
- balance: Totalt saldo i portfolio (0 om saknas)
- current_rate_usdc: Aktuell kurs i USDC
- current_value_usdc: Totalt värde (balance * current_rate, 0 om balance saknas)
- previous_rate_usdc: Senaste köpkurs från trades (0 om ingen trade finns)
- percentage_change: Procentuell förändring sedan köp (0 om ej beräkningsbar)
- value_change_usdc: Absolut värdeförändring i USDC (current_value - (previous_rate * balance), 0 om ej beräkningsbar)

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
export TAKE_PROFIT_PERCENTAGE="10.0"  # Valfritt, standard: 10.0%
export STOP_LOSS_PERCENTAGE="6.0"     # Valfritt, standard: 6.0%
export DRY_RUN="true"

# Kör data collection
python3 -m hunk2.src.main --collect-data

# Kör teknisk analys
python3 -m hunk2.src.main --run-ta

# Kör rebalansering av portfölj
python3 -m hunk2.src.main --rebalance-portfolio
```

## Funktionalitet: Portfolio Rebalancing

Modulen `rebalance_portfolio` genererar köp/säljrekommendationer baserat på teknisk analys och portföljregler:

**Steg 1: TA-poängberäkning**
- RSI_14 < 30: +1 (översålt)
- RSI_14 > 70: -1 (överköpt)
- EMA_12 > EMA_26: +1 (bullish korsning)
- EMA_12 < EMA_26: -1 (bearish korsning)
- MACD > MACD_Signal: +1 (bullish momentum)
- MACD < MACD_Signal: -1 (bearish momentum)
- Close > EMA_200: +1 (över långsiktig trend)
- Close < EMA_200: -1 (under långsiktig trend)

**Signaler:**
- Poäng >= 1: BUY-signal
- Poäng <= -1: SELL-signal

**Steg 2: Portföljregler med prioritering**

**Regel 1 (högsta prioritet):** Ta vinst på små innehav
- Om innehav < TRADE_THRESHOLD OCH vinst > TAKE_PROFIT_PERCENTAGE: SELL
- Standard: 10% vinst, konfigurerbar via TAKE_PROFIT_PERCENTAGE

**Regel 2 (hög prioritet):** Stop loss för större innehav
- Om innehav >= TRADE_THRESHOLD OCH förlust > STOP_LOSS_PERCENTAGE: SELL
- Standard: 6% förlust, konfigurerbar via STOP_LOSS_PERCENTAGE
- Trumfar TA-signaler och skyddar mot stora förluster

**Regel 3:** Skyddsregel för små innehav
- Om innehav < TRADE_THRESHOLD: ingen SELL tillåts (förutom Regel 1)

**Urvalsregler:**
- Max 1 BUY tillåts (välj högst TA-poäng, första vid lika)
- Flera SELL tillåts

**Input:**
- `DATA_AREA_ROOT_DIR/ta/<currency>/<currency>_ta.csv` - TA-signaler
- `DATA_AREA_ROOT_DIR/summarised/portfolio.csv` - Portfolio-sammanställning

**Output:** `DATA_AREA_ROOT_DIR/output/rebalance/recommendations.csv`

CSV-format (output):
- currency: Valutasymbol
- ta_score: TA-poäng
- current_value_usdc: Nuvarande värde i USDC
- percentage_change: Procentuell förändring sedan senaste köp
- signal: BUY eller SELL

**Körning:**
```bash
# Kör rebalansering (kräver att TA och portfolio summary körts först)
python3 -m hunk2.src.main --rebalance-portfolio
```

## Funktionalitet: Trade Plan Creation

Modulen `create_trade_plan` genererar en handelsplan baserat på portfölj och rebalanserings-rekommendationer:

**Steg:**
1. Läser portfölj från `DATA_AREA_ROOT_DIR/summarised/portfolio.csv`
2. Läser rekommendationer från `DATA_AREA_ROOT_DIR/output/rebalance/recommendations.csv`
3. Processar SELL-rekommendationer först: säljer hela innehavet om värde > TRADE_THRESHOLD
4. Beräknar tillgängliga medel efter försäljningar
5. Processar BUY-rekommendationer: köper EN valuta med alla tillgängliga medel om > TRADE_THRESHOLD

**Output:** `DATA_AREA_ROOT_DIR/output/rebalance/trade_plan.csv`

CSV-format (output):
- action: BUY eller SELL
- currency: Valutasymbol
- amount: Kvantitet (eller 'ALL' för BUY)
- value_usdc: Värde i USDC

**Körning:**
```bash
# Skapa handelsplan
python3 -m hunk2.src.main --create-trade-plan
```

## Funktionalitet: Trade Execution

Modulen `execute_trade_plan` utför handel mot Binance enligt handelplanen:

**Funktioner:**
1. Läser handelsplan från `DATA_AREA_ROOT_DIR/output/rebalance/trade_plan.csv`
2. Validerar börsinformation från `BINANCE_BASE_URL/BINANCE_EXCHANGE_INFO_ENDPOINT`
3. Om `DRY_RUN=true`: loggar affärer utan att utföra dem (för testning)
4. Om `DRY_RUN=false`: använder CCXTBroker för att lägga köp/sälj-order på Binance

**Autentisering:**
- Använder `BINANCE_KEY` och `BINANCE_SECRET` från miljövariabler

**Säkerhet:**
- Stöder DRY_RUN-läge för säker testning
- Validerar börsinformation innan handel
- Detaljerad loggning av alla operationer

**Begränsningar:**
- Använder USDC som quote-valuta för alla handelspar
- Lägger market-ordrar (ej limit-ordrar)

**Körning:**
```bash
# Testläge (ingen riktig handel)
export DRY_RUN="true"
python3 -m hunk2.src.main --execute-trades

# Riktiga affärer (var försiktig!)
export DRY_RUN="false"
python3 -m hunk2.src.main --execute-trades
```

## Fullständigt Workflow

```bash
# 1. Sätt miljövariabler
export CURRENCIES="BTC,ETH,SOL"
export BINANCE_KEY="din_key"
export BINANCE_SECRET="din_secret"
export BINANCE_TRADING_URL="https://www.binance.com/api/v3/order"
export DATA_AREA_ROOT_DIR="/path/to/data"
export CURRENCY_HISTORY_PERIOD="1h"
export CURRENCY_HISTORY_NOF_ELEMENTS="300"
export TRADE_THRESHOLD="100.0"
export TAKE_PROFIT_PERCENTAGE="10.0"  # Valfritt, ta vinst vid 10% uppgång
export STOP_LOSS_PERCENTAGE="6.0"     # Valfritt, sälj vid 6% nedgång
export DRY_RUN="true"

# 2. Samla data
python3 -m hunk2.src.main --collect-data

# 3. Kör teknisk analys
python3 -m hunk2.src.main --run-ta

# 4. Generera rekommendationer
python3 -m hunk2.src.main --rebalance-portfolio

# 5. Skapa handelsplan
python3 -m hunk2.src.main --create-trade-plan

# 6. Utför handel (DRY_RUN=true för test)
python3 -m hunk2.src.main --execute-trades
```

## Tester

Tester för modulerna finns i `hunk2/tests/`. Kör tester med:

```bash
python3 -m unittest discover hunk2/tests
```
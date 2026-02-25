# CryptoHunk 2.0

Automated cryptocurrency trading bot with technical analysis and portfolio rebalancing for Binance.

## Features

- Collect market data and portfolio information from Binance
- Technical analysis (RSI, EMA, MACD indicators)
- Portfolio summarization with P&L tracking
- Automated rebalancing recommendations
- Trade plan creation and execution
- Dry-run mode for safe testing

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set required environment variables
export CURRENCIES="BTC,ETH,SOL"
export BINANCE_KEY="your_api_key"
export BINANCE_SECRET="your_api_secret"
export BINANCE_TRADING_URL="https://www.binance.com/api/v3/order"
export DATA_AREA_ROOT_DIR="/path/to/data"
export CURRENCY_HISTORY_PERIOD="1h"
export CURRENCY_HISTORY_NOF_ELEMENTS="300"
export TRADE_THRESHOLD="100.0"
export DRY_RUN="true"

# Run complete workflow (TA strategy)
python3 -m src.main --collect-data
python3 -m src.main --run-ta
python3 -m src.main --rebalance-portfolio
python3 -m src.main --create-trade-plan
python3 -m src.main --execute-trades

# OR: Run with TA2 strategy (--run-ta and --run-ta2 are mutually exclusive)
python3 -m src.main --run-ta2 --rebalance-portfolio
```

## Configuration

### Required Variables
- `CURRENCIES` - Comma-separated list (e.g., "BTC,ETH,SOL")
- `BINANCE_KEY` - Binance API key
- `BINANCE_SECRET` - Binance API secret
- `BINANCE_TRADING_URL` - Binance trading URL
- `DATA_AREA_ROOT_DIR` - Data storage path
- `CURRENCY_HISTORY_PERIOD` - History period (e.g., "1h")
- `CURRENCY_HISTORY_NOF_ELEMENTS` - Number of historical data points
- `TRADE_THRESHOLD` - Minimum trade value in USDC

### Optional Variables (with defaults)
- `TAKE_PROFIT_PERCENTAGE` - Profit target (default: 10.0%)
- `STOP_LOSS_PERCENTAGE` - Loss limit (default: 6.0%)
- `QUOTE_ASSETS` - Quote currencies (default: "USDT,USDC")
- `DRY_RUN` - Test mode without real trades (default: false)
- `TA2_USE_EMA50_FILTER` - Enable EMA50 trend-strength filter for TA2 (default: false)

## Technical Analysis

Calculates indicators on historical price data:
- RSI (14 periods)
- EMA (12, 21, 26, 50, 200 periods)
- MACD with signal line and histogram

Two TA strategies are available:

### TA Strategy (default, `--run-ta`)
**TA Score Calculation:**
- RSI < 30 or > 70: +1/-1 points
- EMA crossovers: +1/-1 points
- MACD signals: +1/-1 points
- Price vs EMA 200: +1/-1 points

### TA2 Strategy (`--run-ta2`) — Long-Only Trend-Following Pullback
**Entry (BUY) — all conditions must be true:**
- `Close > EMA_200` (trend filter)
- `MACD > MACD_Signal` (momentum)
- `Close > EMA_21` (price above short EMA)
- RSI_14 crosses up over 50: `RSI(t-1) <= 50` AND `RSI(t) > 50`
- Pullback reset: `min(RSI_14 over 8 candles before t) < 45`
- Optional: `EMA_50 > EMA_200` if `TA2_USE_EMA50_FILTER=true`

**Exit (SELL):**
- `MACD < MACD_Signal`

`--run-ta` and `--run-ta2` are mutually exclusive. Use one or the other.

## Rebalancing Rules

**TA Score Calculation:**
- RSI < 30 or > 70: +1/-1 points
- EMA crossovers: +1/-1 points
- MACD signals: +1/-1 points
- Price vs EMA 200: +1/-1 points

**Trading Rules:**
1. Take profit on small positions when gain > TAKE_PROFIT_PERCENTAGE
2. Stop loss on large positions when loss > STOP_LOSS_PERCENTAGE
3. No selling positions below TRADE_THRESHOLD (except rule 1)
4. Maximum one BUY per cycle

## Testing

```bash
python3 -m unittest discover tests
```

## Safety

Always use `DRY_RUN=true` for testing. Real trading involves financial risk.
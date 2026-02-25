#!/usr/bin/env bash

export CURRENCIES="BNB,ETH,SOL"
export BINANCE_TRADING_URL="https://www.binance.com/api/v3/order"
export DATA_AREA_ROOT_DIR="/tmp/cryptohunk_data"
export CURRENCY_HISTORY_PERIOD="1h"
export CURRENCY_HISTORY_NOF_ELEMENTS="100"
export TRADE_THRESHOLD="10"
export TAKE_PROFIT_PERCENTAGE="10.0"
export STOP_LOSS_PERCENTAGE="6.0"

#
# sedan:
#   ./run.sh

set -euo pipefail

PYTHON=${PYTHON:-python3}

echo "Kör AssertEnv och main..."
# Default: använd TA-strategi (--run-ta). För att använda TA2-strategi, byt --run-ta mot --run-ta2.
# Exempel med TA2: $PYTHON -m src.main "$@" --clean-data --collect-data --run-ta2 --rebalance-portfolio --create-trade-plan --execute-trades
$PYTHON -m src.main "$@" --clean-data --collect-data --run-ta --rebalance-portfolio --create-trade-plan --execute-trades
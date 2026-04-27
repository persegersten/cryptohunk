#!/usr/bin/env bash

export CURRENCIES="BTC,ETH,SOL"
export BINANCE_TRADING_URL="https://www.binance.com/api/v3/order"
export DATA_AREA_ROOT_DIR="/tmp/cryptohunk_data"
export LOG_FILE="tmp/run.log"
export CURRENCY_HISTORY_PERIOD="1h"
export CURRENCY_HISTORY_NOF_ELEMENTS="1000"
export TRADE_THRESHOLD="10"
export TAKE_PROFIT_PERCENTAGE="3.0"
export STOP_LOSS_PERCENTAGE="3.0"

#
# sedan:
#   ./run.sh

set -euo pipefail

PYTHON=${PYTHON:-python3}

echo "Kör AssertEnv och main..."
$PYTHON -m src.main "$@" --clean-data --collect-data --run-ta --rebalance-portfolio --create-trade-plan --execute-trades --backtest --visualize --ftp-upload 2>&1 | tee "$LOG_FILE"


exit_code=${PIPESTATUS[0]}
set -e

curl --ftp-create-dirs -v \
  --user "$FTP_USERNAME:$FTP_PASSWORD" \
  --upload-file "$LOG_FILE" \
  "ftp://$FTP_HOST/$FTP_DIR/run.log"

exit "$exit_code"
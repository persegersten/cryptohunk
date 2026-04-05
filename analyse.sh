#!/usr/bin/env bash
# Enkel wrapper för att köra CryptoHunk2.0 från kommandoraden.
# Exempel:
export CURRENCIES="BNB,ETH,SOL"
export DATA_AREA_ROOT_DIR="/tmp/cryptohunk_data"
export CURRENCY_HISTORY_PERIOD="1h"
export CURRENCY_HISTORY_NOF_ELEMENTS="1000"

#
# sedan:
#   ./analyse.sh

set -euo pipefail

PYTHON=${PYTHON:-python3}

echo "Kör AssertEnv och main..."
# Disabled, run in run.sh instead
# $PYTHON -m src.main "$@" --clean-data --collect-data --run-ta --backtest --visualize --ftp-upload
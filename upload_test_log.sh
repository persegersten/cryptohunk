#!/usr/bin/env bash

set -euo pipefail

PYTHON=${PYTHON:-python3}
LOG_FILE="/tmp/test.log"

printf '%s\n' "Hellow world" > "$LOG_FILE"

echo "Uploading log file to FTP server..."
"$PYTHON" -m src.ftp_upload "$LOG_FILE"

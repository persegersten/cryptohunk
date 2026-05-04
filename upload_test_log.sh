#!/usr/bin/env bash

export FTP_HOST="ftp.domeneshop.no"
export FTP_DIR="www/cryptohunk"
export FTP_USERNAME="segersten"
export FTP_PASSWORD="sk-Ze-valack-2040-enas"

set -euo pipefail

PYTHON=${PYTHON:-python3}
LOG_FILE="/tmp/test.log"

printf 'Hello world %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" > "$LOG_FILE"

echo "Uploading log file to FTP server..."
"$PYTHON" -m src.ftp_upload "$LOG_FILE"

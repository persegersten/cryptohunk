#!/usr/bin/env bash

export SCHEDULE_FORCE_RUN=true
export TRADE_DRY_RUN=true
export SKIP_DOWNLOAD_HISTORY=false
# export FIXIE_SOCKS_HOST="fixie:J0duPrq3gn6EEdi@bici.usefixie.com:1080"

python src/analyse_and_trade_three_assets_weighted.py
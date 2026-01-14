#!/usr/bin/env python3
"""
Valutor bnb, etherum och solana

 1. Hämta csv-filpath per valuta, kontrollera att det finns exakt 1 fil i vardera bnb_data, etherum_data, solana_data kataloger (locate_input_files)
 2. hämta hem spot-trade historik för kontot (samma api-nycklar används som i run.sh), 
 splitta per valuta och spara som csv-fil per valuta. Spara även orginalfilen som laddades ner
 3. plotta en tidseria per valuta, historik och handel på den valutn
"""

import fetch_trades as ft
import ohlcv_files as of
import plot_history as ph

bnbHistory, ethHistoy, solHistory = of.locate_input_files();

# TODO 
# 1. ändra så att ph's start&end är relativt nu x.antal dagar bakåt
# 2. ändra så att trades plottas 
# 3. Backtracka TA och kör den (obs kräver mer data laddas ner, så om desing krävs,
# ladda ner all historik som krävs )

bnbTrades, ethTrades, solTrades = ft.download_trades()

# bnb
ph.plot_series(save_path='../output/bnb.png')


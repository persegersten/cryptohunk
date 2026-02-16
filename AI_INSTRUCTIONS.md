# AI Instructions for CryptoHunk 2.0

## Project Overview

CryptoHunk 2.0 is a **stateless automated cryptocurrency trading bot** for Binance that uses technical analysis and portfolio rebalancing strategies to make trading decisions. The system is designed to be stateless, meaning each execution cycle operates independently without maintaining persistent state between runs.

### Core Goal
Continue developing stateless crypto trading capabilities towards Binance, ensuring the bot can:
- Collect market data and portfolio information
- Analyze technical indicators
- Generate trade recommendations
- Execute trades automatically (or in dry-run mode)
- All while maintaining a stateless architecture where each cycle is independent

## Architecture Overview

### Stateless Design Principle
The bot follows a **stateless workflow** where:
1. Each execution starts fresh with no memory of previous runs
2. All state is stored in CSV files in the DATA_AREA_ROOT_DIR
3. Data flows through a pipeline of independent modules
4. Each module reads from CSV files, processes, and writes to CSV files
5. No database or persistent application state is maintained

### Workflow Pipeline

The bot operates in 5 main stages (can be run independently or chained):

1. **Data Collection** (`--collect-data`)
   - Fetches market data from Binance API
   - Synchronizes time with Binance server to avoid timestamp errors
   - Collects: currency history, portfolio holdings, trade history
   - Validates collected data
   - Summarizes portfolio with P&L calculations

2. **Technical Analysis** (`--run-ta`)
   - Calculates technical indicators on historical price data
   - Indicators: RSI (14), EMA (12, 26, 200), MACD with signal and histogram
   - Stores results for each configured currency

3. **Portfolio Rebalancing** (`--rebalance-portfolio`)
   - Analyzes TA signals and current holdings
   - Calculates TA scores based on multiple indicators
   - Generates BUY/SELL recommendations with priority rules
   - Applies safety rules (take profit, stop loss, minimum thresholds)

4. **Trade Plan Creation** (`--create-trade-plan`)
   - Converts recommendations into concrete trades
   - Calculates available funds after sells
   - Generates exactly one BUY per cycle (if funds available)
   - Respects trade threshold minimums

5. **Trade Execution** (`--execute-trades`)
   - Executes trade plan against Binance
   - Supports DRY_RUN mode for safe testing
   - Uses CCXT library for reliable order placement

## Technical Stack

### Language & Framework
- **Python 3** (see `.python-version` for specific version)
- Modular architecture with separate modules for each stage

### Key Dependencies
- `requests>=2.28` - HTTP client for Binance API calls
- `python-dotenv>=1.0` - Environment variable management
- `ccxt>=2.8.0` - Cryptocurrency exchange library (for trade execution)
- `pandas>=2.2.0` - Data manipulation and analysis
- `pandas-ta>=0.3.14b` - Technical analysis indicators

### File Structure
```
cryptohunk/
├── src/
│   ├── main.py                    # Orchestrator/entrypoint
│   ├── config.py                  # Configuration dataclass
│   ├── assert_env.py              # Environment validation
│   ├── collect_data.py            # Binance data collection
│   ├── validate_collected_data.py # Data validation
│   ├── summarize_portfolio.py     # Portfolio P&L calculation
│   ├── technical_analysis.py      # TA indicator calculation
│   ├── rebalance_portfolio.py     # Recommendation generation
│   ├── create_trade_plan.py       # Trade plan creation
│   ├── execute_trade_plan.py      # Trade execution via CCXT
│   └── clean_data.py              # Data cleanup utility
├── tests/                         # Unit and integration tests
├── requirements.txt               # Python dependencies
├── README.md                      # User documentation
└── AI_INSTRUCTIONS.md            # This file
```

## Module Responsibilities

### 1. Main Orchestrator (`main.py`)
- Entry point for all operations
- Validates environment configuration
- Routes to appropriate modules based on CLI flags
- Chains operations when needed

### 2. Configuration Management (`config.py`, `assert_env.py`)
- Loads and validates environment variables
- Provides typed configuration object
- Fails fast if required variables are missing

### 3. Data Collection (`collect_data.py`)
- **Time Synchronization**: Syncs with Binance server time to avoid -1021 errors
- Fetches currency history (klines/candlesticks)
- Fetches account balance (portfolio)
- Fetches trade history
- Stores raw data as CSV files

### 4. Data Validation (`validate_collected_data.py`)
- Ensures collected data meets quality requirements
- Validates CSV structure and content

### 5. Portfolio Summarization (`summarize_portfolio.py`)
- Calculates current value of holdings
- Computes profit/loss for each position
- Aggregates liquid funds (quote assets like USDT/USDC)

### 6. Technical Analysis (`technical_analysis.py`)
- Reads historical price data
- Calculates RSI, EMA, MACD indicators using pandas-ta
- Stores TA results for use in rebalancing

### 7. Portfolio Rebalancing (`rebalance_portfolio.py`)
**TA Score Calculation:**
- RSI_14 < 30: +1 (oversold), RSI_14 > 70: -1 (overbought)
- EMA_12 > EMA_26: +1 (bullish), EMA_12 < EMA_26: -1 (bearish)
- MACD > MACD_Signal: +1 (bullish), MACD < MACD_Signal: -1 (bearish)
- Close > EMA_200: +1 (uptrend), Close < EMA_200: -1 (downtrend)

**Trading Rules (in priority order):**
1. **Rule 1 (Highest Priority)**: Take profit on small positions
   - If holdings < TRADE_THRESHOLD AND profit > TAKE_PROFIT_PERCENTAGE → SELL
2. **Rule 2**: Stop loss on large positions
   - If holdings >= TRADE_THRESHOLD AND loss > STOP_LOSS_PERCENTAGE → SELL
3. **Rule 3**: Protect small positions
   - If holdings < TRADE_THRESHOLD → no SELL (unless Rule 1 applies)
4. **TA-based signals**: score >= 1 = BUY, score <= -1 = SELL (after rules above)

### 8. Trade Plan Creation (`create_trade_plan.py`)
- Processes SELL recommendations first
- Calculates available liquid funds after sells
- Executes **maximum ONE BUY per cycle** with available funds
- Only trades if amounts exceed TRADE_THRESHOLD

### 9. Trade Execution (`execute_trade_plan.py`)
- Uses CCXT library to interface with Binance
- Validates exchange info and trading pairs
- Places market orders for configured trades
- Respects DRY_RUN flag for testing

## Configuration

### Required Environment Variables
```bash
CURRENCIES="BTC,ETH,SOL"              # Comma-separated list
BINANCE_KEY="your_api_key"            # Binance API key
BINANCE_SECRET="your_api_secret"      # Binance API secret
BINANCE_TRADING_URL="https://www.binance.com/api/v3/order"
DATA_AREA_ROOT_DIR="/path/to/data"   # Local storage for CSV files
CURRENCY_HISTORY_PERIOD="1h"          # Kline interval (1m, 5m, 1h, 1d, etc.)
CURRENCY_HISTORY_NOF_ELEMENTS="300"   # Number of historical candles
TRADE_THRESHOLD="100.0"               # Minimum trade value in USDC
```

### Optional Environment Variables
```bash
TAKE_PROFIT_PERCENTAGE="10.0"         # Default: 10%
STOP_LOSS_PERCENTAGE="6.0"            # Default: 6%
QUOTE_ASSETS="USDT,USDC"              # Default: "USDT,USDC"
DRY_RUN="true"                        # Default: false
```

## Development Guidelines

### Making Changes

1. **Preserve Stateless Architecture**
   - Never add in-memory state that persists between runs
   - Always read from/write to CSV files
   - Each module should be independently runnable

2. **Minimal Modifications**
   - Make the smallest possible changes to achieve goals
   - Don't refactor unrelated code
   - Maintain existing patterns and conventions

3. **Data Flow Integrity**
   - Understand the CSV schema before modifying
   - Ensure backward compatibility with existing data files
   - Document any schema changes

4. **Error Handling**
   - Fail fast with clear error messages
   - Log errors appropriately
   - Don't silently ignore failures

5. **Binance Integration**
   - Always sync time with Binance server before signed requests
   - Handle rate limits appropriately
   - Use CCXT library for trade execution
   - Test with DRY_RUN before live trading

### Code Style

- **Comments**: Use Swedish for main comments (matches existing code), English for technical terms
- **Logging**: Use Python logging module, not print statements
- **Type Hints**: Use type hints where they add clarity
- **Error Messages**: Clear, actionable error messages in Swedish or English

### Testing

```bash
# Run all tests
python3 -m unittest discover tests

# Run specific test module
python3 -m unittest tests.test_technical_analysis
```

**Testing Strategy:**
- Unit tests for core calculation logic
- Integration tests for full workflow
- Always test with DRY_RUN=true first
- Mock Binance API calls in tests

### Common Development Tasks

**Adding a New Currency:**
1. Add to CURRENCIES environment variable
2. Run `--collect-data` to fetch history
3. System automatically includes in TA and rebalancing

**Modifying TA Indicators:**
1. Edit `technical_analysis.py` calculation methods
2. Update schema documentation if output changes
3. Test with historical data
4. Validate with `rebalance_portfolio.py`

**Adjusting Trading Rules:**
1. Edit `rebalance_portfolio.py` rule logic
2. Update documentation in module docstring
3. Test with various portfolio scenarios
4. Ensure rules apply in correct priority order

**Changing Trade Execution:**
1. Edit `execute_trade_plan.py`
2. Test thoroughly in DRY_RUN mode
3. Start with small TRADE_THRESHOLD values
4. Monitor first live executions closely

## Safety & Best Practices

### Financial Safety
1. **Always test with DRY_RUN=true** before live trading
2. Start with small TRADE_THRESHOLD values
3. Monitor first trades manually
4. Keep TAKE_PROFIT and STOP_LOSS reasonable
5. Never commit API keys to version control

### Data Integrity
1. Validate collected data before analysis
2. Handle missing/corrupt CSV files gracefully
3. Backup DATA_AREA_ROOT_DIR regularly
4. Use `--clean-data` cautiously (it deletes all data)

### API Usage
1. Respect Binance rate limits
2. Handle network errors gracefully
3. Implement retry logic for transient failures
4. Monitor API quota usage

## Debugging Tips

### Common Issues

**-1021 Timestamp Error:**
- System already handles this via time sync
- If it occurs, check system clock accuracy
- Verify internet connectivity

**Empty Portfolio:**
- Ensure Binance API keys have correct permissions
- Check that account has actual holdings
- Verify quote assets (USDT/USDC) are available

**No Trades Generated:**
- Check TRADE_THRESHOLD value (may be too high)
- Review TA scores in `ta/<currency>/<currency>_ta.csv`
- Examine recommendations in `output/rebalance/recommendations.csv`
- Verify available liquid funds

**Failed Trade Execution:**
- Check Binance trading permissions
- Verify trading pair exists (check exchange info)
- Ensure sufficient balance
- Check order size minimums

### Useful Debug Commands

```bash
# Dump configuration
python3 -m src.main --dump-config

# Run with verbose logging
python3 -m src.main --collect-data 2>&1 | tee debug.log

# Inspect generated files
cat DATA_AREA_ROOT_DIR/output/rebalance/recommendations.csv
cat DATA_AREA_ROOT_DIR/output/rebalance/trade_plan.csv
```

## Future Development Ideas

### Potential Enhancements
1. Support for more exchanges beyond Binance
2. Additional technical indicators (Bollinger Bands, Stochastic, etc.)
3. Multiple buy strategies per cycle
4. Position sizing based on portfolio percentage
5. Trailing stop losses
6. Backtesting framework
7. Web dashboard for monitoring
8. Telegram/email notifications
9. Advanced risk management (max drawdown, correlation analysis)
10. Machine learning for signal optimization

### Maintaining Statelessness
When adding features, remember:
- State goes in CSV files, never in memory
- Each module should be independently testable
- Clear data dependencies between modules
- Pipeline should be easily debuggable by inspecting CSV files

## Questions to Ask When Working on This Project

1. **Is my change stateless?** Can the system restart and continue correctly?
2. **Does it affect CSV schemas?** Document any changes.
3. **Did I test with DRY_RUN?** Never skip dry run testing.
4. **Are errors handled gracefully?** System should fail clearly, not silently.
5. **Did I respect the pipeline order?** Don't skip prerequisite stages.
6. **Is the change minimal?** Don't over-engineer solutions.
7. **Does it maintain backward compatibility?** Old data files should still work.

## Getting Help

- **README.md**: User-focused documentation and quick start
- **Module docstrings**: Detailed documentation of each component
- **Test files**: Examples of how modules should behave
- **CSV files in DATA_AREA_ROOT_DIR**: Actual data schemas and examples

---

**Remember**: This is a financial trading system. Prioritize correctness, safety, and thorough testing above all else. When in doubt, use DRY_RUN mode and validate manually.

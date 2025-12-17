# Cryptohunk — crypto data & portfolio tools
<table>
<tr>
<td>
A compact collection of Python tools for fetching OHLCV data, analysing a small multi-asset portfolio, and running a simple technical-analysis (TA) agent + rebalancer. This README is pragmatic and focused: how to run locally for development/debugging (local.sh) and how the container entrypoint should run in the cloud (run.sh).
</td>
<td style="vertical-align: top;">
<img src="images/hunk.png" width="350"/>
</td>
</tr>
</table>

---

## Quick overview

- Run the full pipeline locally for development and dry-runs with `local.sh`.
- In cloud environments, `run.sh` is the container entrypoint and expects required configuration via environment variables.
- The repo includes scripts to download market data (Binance / CoinGecko), portfolio and trade history, run the TA agent, and rebalance a portfolio.

---

## Repo layout

- `.python-version` — recommended Python version
- `requirements.txt` — Python dependencies
- `Procfile` — optional (Heroku-like PaaS)
- `run.sh`, `binance_debug.sh`, `noop.sh` — helper and entrypoint scripts
- `src/` — main Python scripts, e.g.:
  - data: `download_binance_ohlcv.py`, `download_coingecko_ohlcv.py`
  - portfolio: `download_portfolio.py`, `download_trade_history.py`
  - agent/rebalance: `ta_signal_agent_live_three_assets.py`, `analyse_and_trade_three_assets_weighted.py`, `portfolio_rebalancer.py`
  - utilities: `schedule_gate.py`, `heroku_ip_proxy.py`
  - tests: `test_*` scripts for connectivity and health checks

---

## Requirements

- Git
- Python (match `.python-version`; pyenv recommended)
- pip
- venv or virtualenv
- Exchange API keys (Binance / CCXT) for private endpoints
- (Optional) Docker for containerised runs

Do not commit secrets. Use your platform's secret manager or orchestration secrets.

---

## Environment variables (container must provide)

Common variables used across scripts:

- CCXT_API_KEY — Binance API key
- CCXT_API_SECRET — Binance API secret
- FIXIE_SOCKS_HOST — proxy (optional)
- SCHEDULE_FORCE_RUN — set `true` to bypass scheduler and always run TA + rebalancer
- SCHEDULE_GRACE_MINUTES - default is 5
- SCHEDULE_AT_HOURS - default is 0, 4, 8, 12, 16, 20
- SCHEDULE_TIME_ZONE - default is Europe/Stockholm
- SKIP_DOWNLOAD_HISTORY — set `true` to skip downloading spot trade history (useful for repeated local runs)
- TRADE_DRY_RUN — set `true` to avoid executing live trades

---

## Local development (recommended)

1. Clone:
   - git clone https://github.com/persegersten/cryptohunk.git
   - cd cryptohunk

2. Prepare Python:
   - pyenv install $(cat .python-version)  # optional
   - python -m venv .venv
   - source .venv/bin/activate
   - pip install -r requirements.txt

3. Install and configure `local.sh`:
   - cp local.sh.template local.sh
   - Edit `local.sh` to add environment variables (do not commit)
   - chmod +x local.sh
   - ./local.sh

`local.sh` is the recommended developer entrypoint for debugging and dry-runs.

---

## Cloud / Production (run.sh)

- Containers must inject required environment variables (secrets, proxy, config).
- `run.sh` is the intended entrypoint for cloud runs — do not hardcode secrets.
- Example Docker command (conceptual):
  - CMD ["./run.sh"]

For periodic execution use a process manager, CronJob, or Kubernetes CronJob. For continuous execution run the container as a worker.

---

## Quick safety checklist

- Run tests before live trading:
  - python src/test_binance_spot_key.py
  - python src/test_binance_health_check.py
- Use dry-run (`CRYPTOHUNK_DRYRUN=1` or `TRADE_DRY_RUN=true`) and inspect behavior.
- Prefer testnet accounts / limited balances before enabling live trading.

---

## Deployment hints

- Heroku: use `Procfile`, set config vars, use Heroku Scheduler or run a worker.
- Docker: inject secrets from the platform; avoid storing secrets in images.
- Kubernetes: use Secrets, Deployments or CronJobs, and health probes.
- VMs: use systemd or cron; inject secrets from your cloud provider.

---

## Logging & monitoring

- Ensure stdout/stderr are collected by your platform logging driver.
- Forward logs to central systems (CloudWatch, Stackdriver, Papertrail).
- Add alerts for error rates, failed downloads, and trade execution failures.

---

## Reference

Image: August Wilhelm Johnson — "The Lion from Scandinavia" (https://sv.wikipedia.org/wiki/August_Wilhelm_Johnson)
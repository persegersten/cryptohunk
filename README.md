<table>
<tr>
<td># Cryptohunk — crypto data & portfolio tools

A compact collection of Python tools for fetching OHLCV data, analysing a small multi-asset portfolio and running a simple technical-analysis (TA) agent and rebalancer.

This README is pragmatic and focused: how to start the whole application locally for development/debugging (via local.sh) and how the cloud container should run it (via run.sh), plus the minimal hints you need to deploy.
</td>
<td style="vertical-align: top;">

<img src="images/hunk.png" width="250"/>

</td>
</tr>
</table>

---

## Short summary / intent

- Start the full pipeline locally from your laptop using local.sh (for development, debugging, dry-runs).
- In cloud environments the container / orchestration is responsible for providing all environment variables; run.sh is the runtime entrypoint used by the cloud container.
- The codebase contains scripts for downloading market data (Binance / CoinGecko), downloading portfolio/trade-history, running the TA agent and rebalancer. The recommended developer workflow is to run the whole pipeline via local.sh which orchestrates the same steps run.sh runs in production.

---

## Repo layout (high level)

- `.python-version` — recommended Python version
- `requirements.txt` — Python dependencies
- `Procfile` — process declaration for Heroku-like PaaS (optional)
- `run.sh` — cloud entrypoint (expects env vars provided by container)
- `binance_debug.sh`, `noop.sh`, `run.sh` — helper scripts
- `src/` — main Python scripts:
  - download_binance_ohlcv.py, download_coingecko_ohlcv.py
  - download_portfolio.py, download_trade_history.py
  - ta_signal_agent_live_three_assets.py (main agent)
  - analyse_and_trade_three_assets_weighted.py
  - portfolio_rebalancer.py
  - schedule_gate.py, heroku_ip_proxy.py
  - test_* scripts for connectivity/health checks

---

## Quick prerequisites

- Git
- Python (match `.python-version`; pyenv recommended)
- pip
- Virtualenv (or venv)
- API keys for exchanges (Binance / CCXT) if you intend to hit private endpoints
- (Optional) Docker for containerized runs

---

## Environment variables

The cloud container must provide the secrets and config through environment variables. Typical variables used across scripts:

- BINANCE_API_KEY
- BINANCE_API_SECRET (or BINANCE_SECRET depending on script)
- CCXT_API_KEY (alternate key name found in some helpers)
- CCXT_API_SECRET
- FIXIE_SOCKS_HOST (optional proxy)
- PROXY_URL (optional)
- Any other environment variables your deployment or monitoring expects (LOG_LEVEL, DATA_DIR, etc.)

Important: Do not commit keys into git. Use your cloud provider’s secret manager or container orchestration secret features.

---

## Local development workflow (use local.sh)

local.sh is the recommended developer entrypoint: it sets local-friendly environment variables (or loads them from a local .env file), enables dry-run mode and then calls the same pipeline invoked by run.sh so your local run closely mirrors production.

Suggested local.sh (example you can create at repo root):

```bash
#!/usr/bin/env bash
set -euo pipefail

# Example local.sh — adjust to your environment.
# Load .env if present (optional, do NOT commit .env)
if [ -f .env ]; then
  # Use a simple .env loader; keep secrets out of git
  export $(grep -v '^#' .env | xargs)
fi

# Set developer-friendly defaults (override in .env or env)
export LOG_LEVEL="${LOG_LEVEL:-DEBUG}"
# Set dry-run so no live orders are sent
export CRYPTOHUNK_DRYRUN="1"

# Optionally set minimal example API keys for read-only endpoints
# export BINANCE_API_KEY="..."
# export BINANCE_API_SECRET="..."

# Ensure expected folders exist for downloaded CSVs
mkdir -p bnb_data ethereum_data solana_data history

# Run the same pipeline as run.sh but in local/dry-run mode
# If run.sh supports flags you can forward them here (e.g., --dry-run)
./run.sh
```

How to use local.sh:
- Make executable: chmod +x local.sh
- Create a local .env with your dev env vars (untracked), or export variables in shell
- ./local.sh

local.sh should be used for iterative testing, debugging and validating your connectivity / data pipeline before deploying to cloud.

---

## Production / Cloud usage (run.sh)

- In the cloud, containers must provide all required environment variables (secrets, proxy, config).
- The container or init system should call run.sh (it is the intended entrypoint for the cloud environment).
- run.sh can rely on environment variables being injected by the orchestrator; it should not hardcode secrets.

Typical container flow:
- Container image includes code and dependencies
- Secrets are injected by the platform (Kubernetes Secrets, ECS Parameter Store/Secrets Manager, Heroku config vars)
- The container command (or entrypoint) runs: ./run.sh

Example Docker CMD (conceptual):

```dockerfile
CMD ["./run.sh"]
```

If you want the container to execute the pipeline periodically, run a process manager or create a CronJob / Kubernetes CronJob. Alternatively, run the container as a continuously running worker.

---

## Basic local quickstart

1. Clone
   - git clone https://github.com/persegersten/cryptohunk.git
   - cd cryptohunk

2. Prepare Python
   - pyenv install $(cat .python-version)  # optional
   - python -m venv .venv
   - source .venv/bin/activate
   - pip install -r requirements.txt

3. Create .env (optional, untracked) with keys for local work:
   - BINANCE_API_KEY=...
   - BINANCE_API_SECRET=...
   - LOG_LEVEL=DEBUG

4. Make local.sh executable and run it:
   - chmod +x local.sh
   - ./local.sh

5. For cloud runs, ensure run.sh is executable and call it from your container (env vars injected by the platform):
   - chmod +x run.sh
   - ./run.sh  (the container should already have the env set)

---

## Tests and safety checks

- Use the test scripts before live trading:
  - python src/test_binance_spot_key.py
  - python src/test_binance_health_check.py
- Keep a dry-run mode for the agent (set CRYPTOHUNK_DRYRUN=1 or use any flags provided by the agent) and validate behaviour thoroughly.
- Consider using a testnet account and limited balances before enabling live trading.

---

## Deployment hints (practical)

- Heroku: use Procfile, set config vars, scale a worker to run the agent. Use Heroku Scheduler for periodic tasks. Ensure secrets are set via `heroku config:set`.
- Docker: build an image, keep run.sh as CMD/entrypoint; inject secrets using the platform or `docker run -e` (avoid using docker-compose for production secrets).
- Kubernetes: build an image, run as Deployment or CronJob; store secrets in Secrets and mount as env vars; use liveness/readiness probes.
- Cloud VMs: use systemd or cron to run run.sh; store secrets in cloud secret manager or environment injection.

---

## Logging / monitoring

- Make sure stdout/stderr are captured by your platform logging driver.
- Send logs to a central system (CloudWatch, Stackdriver, Papertrail) for production runs.
- Add alerts around error rate, failed downloads and trade execution.

## References
The image - August Wilhelm Johnson, known as "The Lion from Scandinavia" https://sv.wikipedia.org/wiki/August_Wilhelm_Johnson
# OI Dashboard

ITM OI + Volume dashboard using TradingView Lightweight Charts. Based on `OI_Newdb_v2/scripts/oi_volume_dashboard.py`.

## Features

- **Exchange**: NSE / BSE
- **Date range**: From / To
- **Charts**:
  - 1m candlesticks + trade markers (entry/exit)
  - ITM CE/PE OI % change (3m wavg) and Volume % change (3m wavg)
- **Trade filter**: All / Profit only / Loss only

## CI/CD

GitHub Actions runs on every push and pull request to `main`:

- **Test**: installs dependencies, checks Python syntax, and runs a quick import check (Python 3.10 and 3.11).
- **Lint**: runs [Ruff](https://docs.astral.sh/ruff/) for linting and format checking.
- **Deploy** (push to `main` only): builds a Docker image and pushes it to [GitHub Container Registry](https://ghcr.io) as `ghcr.io/<owner>/oi-dashboard:latest` and `ghcr.io/<owner>/oi-dashboard:<sha>`.

To fix lint/format locally: `pip install ruff` then `ruff check . --fix` and `ruff format .`.

### Run with Docker

**Option A – Build and run locally** (no GHCR needed):

```bash
docker build -t oi-dashboard .
docker run -p 5055:5055 --env-file .env oi-dashboard
```

**Option B – Pull from GitHub Container Registry (GHCR)**

GHCR images are **private by default**, so you must either log in or make the package public.

1. **Log in to GHCR** (use a [Personal Access Token](https://github.com/settings/tokens) with `read:packages`):

   ```bash
   echo YOUR_GITHUB_TOKEN | docker login ghcr.io -u kpalastro --password-stdin
   docker pull ghcr.io/kpalastro/oi-dashboard:latest
   docker run -p 5055:5055 --env-file .env ghcr.io/kpalastro/oi-dashboard:latest
   ```

2. **Or make the package public** so anyone can pull without logging in:
   - GitHub → your profile → **Packages** → **oi-dashboard** → **Package settings** → **Danger zone** → **Change visibility** → **Public**

**Deploy to production (Ubuntu):** see [DEPLOY.md](DEPLOY.md) for Docker, systemd, and optional Nginx/HTTPS.

**PostgreSQL in another container:** Inside the app container, `localhost` is the container itself, not the host or other containers. Set `OI_TRACKER_DB_HOST` to:

- The **PostgreSQL container name** (e.g. `postgres` or `db`) when both containers are on the same Docker network, or
- **`host.docker.internal`** when PostgreSQL runs on the host (e.g. Docker Desktop on Mac/Windows).

Example (same network): `docker run --network mynet -p 5055:5055 -e OI_TRACKER_DB_HOST=postgres -e OI_TRACKER_DB_PORT=5433 --env-file .env oi-dashboard`

## Setup

1. Copy `.env` and set PostgreSQL and Flask options:

   ```env
   OI_TRACKER_DB_TYPE=postgres
   OI_TRACKER_DB_HOST=localhost
   OI_TRACKER_DB_PORT=5432
   OI_TRACKER_DB_NAME=oi_db_live
   OI_TRACKER_DB_USER=root
   OI_TRACKER_DB_PASSWORD=password

   FLASK_HOST=0.0.0.0
   FLASK_PORT=5055
   ```

   Optional: point trade logs to the other project:

   ```env
   OI_TRACKER_TRADE_LOG_DIR=/path/to/OI_Newdb_v2/trade_logs
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Run

From the project root (`OI_Dashboard`):

```bash
python scripts/oi_volume_dashboard.py
```

Then open in the browser:

- **http://127.0.0.1:5055/** (or the host/port from `.env`)

## Database

Expects the same schema as OI_Newdb_v2:

- `ml_features` (timestamp, exchange, itm_oi_ce_pct_change_3m_wavg, itm_oi_pe_pct_change_3m_wavg, feature_payload)
- `multi_resolution_bars` (timestamp, exchange, symbol, resolution, open_price, high_price, low_price, close_price, volume, oi)
- Views: `daily_pnl_report_view` (daily summary), `paper_trades_signal_changes_view` (BUY/SELL signals for chart markers; no direct use of `paper_trading_metrics`)

Trade markers are loaded from CSV files under `trade_logs/` (or `OI_TRACKER_TRADE_LOG_DIR`), e.g. `trade_logs/trades_YYYY-MM-DD.csv`.

## Backtest Fib previous-day strategy (futures)

Backtest the Fibonacci previous-day high/low strategy on **futures** (December future for December, January for January, etc.) from 1 December to latest data in DB, for both BSE and NSE:

```bash
python scripts/backtest_fib_prev_day.py --start 2025-12-01
python scripts/backtest_fib_prev_day.py --start 2025-12-01 --daily
```

- **Best intraday (default):** Grid search over entry level (0.382, 0.5, 0.618, 0.786), target extension (1.11, 1.272), stop buffer (10–25 pts), and sides (both / long_only / short_only). Reports the best params and PnL per exchange. Use `--no-best` for fixed params (0.618, 1.11, 15, both). Use `--quick` for fewer combos.
- Uses `multi_resolution_bars` (1m/5m) for prev day H/L and intraday bars.
- Picks symbol by month: DEC future for Dec, JAN for Jan, etc.; falls back to symbol with data if no month match.
- One trade per day: first Fib-level bounce = long, first rejection = short; target 1.11/1.272 extension, stop at entry level ± buffer.
- `--daily` prints each day’s outcome (symbol, side, PnL) and combined NSE+BSE.

## Backtest OI/Vol strategy (no paper signals)

Find the best rule-based strategy using **only** ITM CE/PE OI % Change (3m wavg) and Volume % Change (3m wavg), day-by-day, ignoring existing paper-trade signals:

```bash
python scripts/backtest_oi_vol_strategy.py --start 2026-01-19 --end 2026-01-31 --exchange BSE --exchange NSE --top 5 --daily
```

- **`--quick`**: fewer rule/threshold/hold combinations (faster).
- **Rules tried**: `oi_spread` (CE OI % − PE OI %), `vol_spread`, `oi_plus_vol`, `pe_dominance`.
- **Output**: best strategy (rule, threshold, hold_bars) and total/daily PnL in points; optionally daily breakdown with `--daily`.
